# Resume Extraction Pipeline Architecture

This document outlines the high-level architecture and processing flow of the Resume Extraction Project.

## Processing Workflow

```mermaid
graph TD
    Client([CLIENT: POST /extract/resume PDF]) --> Val[1. File Validation]
    
    subgraph Validation [Validation Tier]
        Val --> Sec[Security Scan: upload_security.py]
        Sec --> Lock[Unlock Handle: pdf_unlock.py]
    end
    
    Lock --> Det[2. Source Detection]
    
    subgraph Detection [app/core/pipeline.py]
        Det --> Classify{PDF Type?}
        Classify -- Digital --> Digi[extract_digital]
        Classify -- Scanned --> Scan[extract_scanned]
    end
    
    subgraph Extraction [Extraction Engines]
        Digi --> DigiP[PyMuPDF + pdfplumber]
        Scan --> ScanP[OpenCV + PaddleOCR]
    end
    
    DigiP --> Text[3. Unified Text Object]
    ScanP --> Text
    
    Text --> Layout[4. Layout Parsing]
    Layout -- DOCEX_RESUME_LAYOUT=1 --> PP[PP-Structure / Reading Order]
    
    PP --> Parser[5. Core Resume Parser]
    
    subgraph Core [app/extraction/]
        Parser --> Seg[Section segmentation]
        Seg --> Field[Field Identification]
        Field --> Links[Apply Hidden Links]
    end
    
    Links --> Enh[6. Enhancement Layer]
    Enh -- DOCEX_RESUME_ENHANCE=1 --> EnhL[NLP Repair / Skill Normalization]
    
    EnhL --> Build[7. JSON Build]
    
    Build --> Persist[8. Hybrid Persistence]
    
    subgraph Persistence [app/database/hybrid_repository.py]
        Persist --> Legacy[Track A: Legacy CRM Tables]
        Persist --> Norm[Track B: Normalized T2O Tables]
    end
    
    Legacy --> Resp([9. Final JSON Response])
    Norm --> Resp
```

## Detailed Component Breakdown

┌──────────────────────────────┐
│  **CLIENT**                    │
│  [POST /api/v1/extract/resume](app/api/routes/extract.py) (PDF) │
└───────────────┬──────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ **1. FILE VALIDATION**                      [run_pipeline](app/core/pipeline.py)      │
│    • `assert_upload_safe` (Magic Bytes, JS)  [upload_security.py](app/security/upload_security.py) │
│    • `unlock_pdf` (Remove Owner Passwords)   [pdf_unlock.py](app/security/pdf_unlock.py)           │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ **2. SOURCE DETECTION**                     [pipeline.py](app/core/pipeline.py)         │
│    `classify_source` → **DIGITAL_PDF**  |  **SCANNED_PDF / IMAGE**          │
└───────┬───────────────────────────────────────┬──────────────────────────┘
        │ *digital path*                         │ *scanned path*
        ▼                                        ▼
┌───────────────────────────┐      ┌─────────────────────────────────────┐
│ **extract_digital**       │      │ **extract_scanned**    [ocr_parser.py](app/core/ocr_parser.py) │
│ [digital_parser.py](app/core/digital_parser.py) │      │ • OpenCV Preprocessing            │
│ • PyMuPDF + pdfplumber    │      │ • PaddleOCR / Tesseract           │
│ • Hidden Link Extraction  │      │ • Barcode-mask & Deskew           │
└───────────┬───────────────┘      └──────────────────┬───────────────────┘
            └──────────────────┬───────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ **3. UNIFIED TEXT**  (`ExtractedText` model: pages → text + tables)       │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ **4. LAYOUT PARSING** [Env: `DOCEX_RESUME_LAYOUT`] [layout_analyzer.py](app/core/layout_analyzer.py) │
│    PP-Structure → reading order / columns / titles / tables               │
│    *Fail-safe: fall back to raw text on analysis error*                   │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ **5. RESUME PARSER (Core)**                 [app/extraction/](app/extraction/)         │
│    • Contact / Name / Address / Headline / Summary                        │
│    • `_segment` → Match section headers via aliases & regex               │
│    • `_build_section` → Experience, Education, Skills, Projects, etc.     │
│    • `_apply_hidden_links` (LinkedIn, GitHub, Portfolio injection)        │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ **6. ENHANCEMENT LAYER** [Env: `DOCEX_RESUME_ENHANCE`] [resume_enhancer.py](app/enhancement/resume_enhancer.py) │
│    • Normalize dates (E1)    • Skill splitting (E5)                       │
│    • Section recovery (E2)   • spaCy NER Entities (E6)                    │
│    • Field repairs (E4)      • Cert-URL mapping (E7)                      │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ **7. JSON BUILD**                           [extract.py](app/api/routes/extract.py)    │
│    `payload = { resume{…sections}, validation, confidence }`              │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ **8. HYBRID PERSIST** `insert_extraction`   [hybrid_repository.py](app/database/hybrid_repository.py) │
│   ┌─ **LEGACY TRACK** ──────────────┐  ┌─ **NORMALIZED T2O TRACK** ───────┐ │
│   │ `IAPL_CRM_RESUME_PROFILE`       │  │ `Candidates_text_to_ocr`         │ │
│   │ `IAPL_CRM_RESUME_SECTION_ITEM`  │  │ `Work_text_to_ocr` (+raw)        │ │
│   └─────────────────────────────────┘  │ `Skills_text_to_ocr` (+raw)      │ │
│                                        │ `Resume_Raw_Data_text_to_ocr`    │ │
│   *Best-effort: T2O failures never*     └──────────────────────────────────┘ │
│   *break the legacy CRM insertion*                                          │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ **9. RESPONSE** → JSON                                                  │
│    `{ resume, mapped, validation, confidence, extraction_id, db }`        │
└─────────────────────────────────────────────────────────────────────────┘
