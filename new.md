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
        Classify -- Digital --> Digi[extract_digital: digital_parser.py]
        Classify -- Scanned --> Scan[extract_scanned: ocr_parser.py]
    end
    
    subgraph Extraction [Extraction Engines]
        Digi --> DigiP[PyMuPDF + pdfplumber]
        Scan --> ScanP[OpenCV + PaddleOCR]
    end
    
    DigiP --> Text[3. Unified Text Object]
    ScanP --> Text
    
    Text --> Layout[4. Layout Parsing: layout_analyzer.py]
    Layout -- DOCEX_RESUME_LAYOUT=1 --> PP[PP-Structure / Reading Order]
    
    PP --> Parser[5. Core Resume Parser: app/extraction/]
    
    subgraph Core [Logic Layer]
        Parser --> Seg[Section segmentation]
        Seg --> Field[Field Identification]
        Field --> Links[Apply Hidden Links]
    end
    
    Links --> Enh[6. Enhancement Layer: resume_enhancer.py]
    Enh -- DOCEX_RESUME_ENHANCE=1 --> EnhL[NLP Repair / Skill Normalization]
    
    EnhL --> Build[7. JSON Build: extract.py]
    
    Build --> Persist[8. Hybrid Persistence: hybrid_repository.py]
    
    subgraph Persistence [Database Tier]
        Persist --> Legacy[Track A: Legacy CRM]
        Persist --> Norm[Track B: Normalized T2O]
    end
    
    Legacy --> Resp([9. Final JSON Response])
    Norm --> Resp
```

## Detailed Component Breakdown

```text
┌──────────────────────────────┐
│  CLIENT                       │
│  POST /extract/resume (PDF)   │
└───────────────┬──────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. FILE VALIDATION                         resume_api.py                  │
│    • assert_upload_safe (type / size / security)   upload_security.py     │
│    • unlock_pdf (password-protected?)              pdf_unlock.py          │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. SOURCE DETECTION                        pipeline.py                     │
│    classify_source → DIGITAL_PDF  |  SCANNED_PDF / IMAGE                   │
└───────┬───────────────────────────────────────┬──────────────────────────┘
        │ digital                                │ scanned / image
        ▼                                        ▼
┌───────────────────────────┐      ┌─────────────────────────────────────┐
│ extract_digital           │      │ extract_scanned        extract.py    │
│   PyMuPDF + pdfplumber     │      │   OpenCV preprocess (deskew, denoise │
│   + hidden hyperlinks      │      │   barcode-mask, OSD) → PaddleOCR /   │
│            extract.py      │      │   Tesseract                          │
└───────────┬───────────────┘      └──────────────────┬───────────────────┘
            └──────────────────┬───────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. UNIFIED TEXT  (ExtractedText: pages → text + tables)                    │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. LAYOUT PARSING  [ON • DOCEX_RESUME_LAYOUT=1]      layout_parser.py      │
│    PP-Structure → reading order / columns / titles                        │
│    fail-safe: on any error → original text                                │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 5. RESUME PARSER (core)                     resume.py                      │
│    • contact / name / address / headline                                  │
│    • _segment  → _match_section_header  (header + despace + aliases)       │
│    • _build_section → experience / education / skill / project /           │
│      certification / language / achievement items                         │
│    • _apply_hidden_links (fill empty LinkedIn/GitHub/Portfolio)            │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 6. ENHANCEMENT LAYER  [OFF • DOCEX_RESUME_ENHANCE=0]  resume_enhance.py    │
│    ──── currently SKIPPED (no-op) ────                                     │
│    (normalize · section-recovery · headerless-exp · field-repairs ·       │
│     skill-split · validator · fuzzy · spaCy entities · cert-url mapper)    │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 7. JSON BUILD                               resume_api.py / schema.py      │
│    payload = { resume{…sections}, validation, confidence,                  │
│               mapped = build_resume_t2o(doc) }      db/procedures.py       │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 8. PERSIST  insert_extraction()                     db/procedures.py       │
│   ┌─ legacy ──────────────────────┐  ┌─ normalized *_text_to_ocr ───────┐ │
│   │ IAPL_CRM_RESUME_PROFILE        │  │ Candidates_text_to_ocr           │ │
│   │ IAPL_CRM_RESUME_SECTION_ITEM   │  │  (+ file_path, inserted_date,    │ │
│   └────────────────────────────────┘  │   inserted_by)                   │ │
│                                        │ Educations_text_to_ocr (+raw_text)│ │
│   best-effort: t2o failure never       │ Companies / Skills / Languages / │ │
│   breaks the legacy insert              │ Work / Projects / Certs / …      │ │
│                                        │ Resume_Raw_Data_text_to_ocr      │ │
│                                        │  (raw_text_resume + json_data)   │ │
│                                        └──────────────────────────────────┘ │
└───────────────┬───────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 9. RESPONSE  → JSON  { resume, mapped, validation,                         │
│                       confidence, extraction_id, db, source_file_url }     │
└───────────────────────────────────────────────────────────────────────────┘
```
