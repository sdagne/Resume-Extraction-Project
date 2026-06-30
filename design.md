# Project Design: Resume - Extraction Project

## Summary
The **Resume - Extraction Project** is a high-performance, non-LLM based resume processing system. Its core objective is to convert diverse PDF resumes (both digital and scanned) into highly structured, validated JSON data. The system focuses on handling complex layouts, such as multi-column designs and sidebars, while providing confidence scoring for each extracted field to ensure reliability.

## Architecture Overview
The system follows a modular, pipeline-oriented architecture built on **FastAPI**. It is designed for scalability and maintainability, separating the ingestion layer from the core analytical logic.

- **API Layer**: Exposes endpoints for file ingestion, extraction management, and data export.
- **Orchestration Pipeline**: A centralized `ExtractionPipeline` that sequences complex operations like OCR, layout analysis, and NLP-based field extraction.
- **Core Engine**: Implements the heavy lifting for PDF parsing (digital and OCR), layout detection, and reading order reconstruction.
- **Extraction Logic**: A suite of specialized extractors that use NLP models, regex, and heuristics to identify sections (Experience, Education, Skills, etc.).
- **Data Layer**: Uses a Repository pattern with **SQLAlchemy** for persistence and **Pydantic** for rigorous data validation.

## Module Communication
The following steps outline the lifecycle of a request:

1.  **Ingestion**: A user uploads a file through the `upload_router`. The file is securely stored via the `storage` module.
2.  **Detection**: The `pdf_detector` identifies if the document is a "native" digital PDF or a scanned image.
3.  **Parsing**:
    - **Digital**: Processed via `PyMuPDF` for fast text extraction.
    - **Scanned**: Routed through the `ocr_parser` using `PaddleOCR`.
4.  **Layout Analysis**: The `layout_analyzer` detects columns, headers, and sidebars to ensure the text is processed in the correct reading order.
5.  **Multi-Stage Extraction**: The text is passed to the `field_extractor`, which delegates tasks to specific sub-modules (e.g., `contact_extractor`, `skills_extractor`).
6.  **Refinement**: Extracted entities are normalized (e.g., job titles standardized, skills matched against a taxonomy).
7.  **Finalization**: Data is validated against the `ExtractedResumeSchema`. A confidence score is calculated, and the result is saved to the PostgreSQL database via the `resume_repository`.

## File Structure Description

| Directory | Responsibility |
| :--- | :--- |
| `app/api/` | Route definitions (`upload`, `extract`, `export`) and custom middleware (logging, error handling). |
| `app/core/` | The engine's "brain." Contains the extraction pipeline, OCR logic, and layout analysis algorithms. |
| `app/extraction/` | Domain-specific extractors for different resume sections (Contact, Experience, Education, etc.). |
| `app/models/` | SQLAlchemy models for the database and Pydantic schemas for API request/response validation. |
| `app/database/` | Database connection management, migrations (Alembic), and the repository layer. |
| `app/nlp/` | Wrappers for NLP engines like **Spacy** used for NER and semantic analysis. |
| `app/matching/` | Logic for normalizing job titles and matching skills against a master taxonomy. |
| `app/export/` | Generators for converting extracted data into Excel (`.xlsx`) or CSV formats. |
| `app/storage/` | Local and cloud (S3) file management, including temporary file cleanup. |
| `app/utils/` | Shared helpers, constants, regex patterns, and logging configuration. |

## Technical Stack

- **Backend Framework**: FastAPI (Asynchronous Python)
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Migrations**: Alembic
- **PDF Processing**: PyMuPDF (fitz), pdfplumber
- **OCR Engine**: PaddleOCR / PaddlePaddle
- **NLP**: Spacy (`en_core_web_md`)
- **Validation**: Pydantic v2
- **Layout Analysis**: LayoutParser
- **Data Handling**: Pandas, RapidFuzz (for skill matching)
- **Export**: Openpyxl
- **Logging**: Loguru
