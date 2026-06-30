# Resume Extraction Project

A professional pipeline for extracting structured data from digital and scanned resumes.

# 📄 Resume Extractor API

A production-ready, high-accuracy resume extraction system that
converts PDF resumes into structured JSON — **without any LLM**.

---

## 🏗️ Architecture

```
Upload → PDF Detection → Text Extraction → Layout Analysis
       → Field Extraction → Skill Matching → Validation
       → Confidence Scoring → Export (Excel/CSV)
```

---

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/yourorg/resume-extractor.git
cd resume-extractor
cp .env.example .env
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_md
```

### 3. Start with Docker

```bash
docker-compose up --build
```

### 4. Start Locally

```bash
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

---

## 📦 Tech Stack

| Layer            | Technology                        |
|------------------|-----------------------------------|
| API Framework    | FastAPI + Uvicorn                 |
| Digital PDF      | PyMuPDF + pdfplumber              |
| Scanned PDF      | PaddleOCR + PP-Structure          |
| Layout Analysis  | Geometric + heuristic analysis    |
| NLP / NER        | spaCy (en_core_web_md)            |
| Skill Matching   | RapidFuzz + ESCO taxonomy         |
| Database         | PostgreSQL + SQLAlchemy           |
| Export           | openpyxl (Excel) + pandas (CSV)   |
| Containerization | Docker + Docker Compose           |

---

## 🔌 API Endpoints

| Method | Endpoint                        | Description              |
|--------|---------------------------------|--------------------------|
| POST   | `/api/v1/upload/`               | Upload single resume     |
| POST   | `/api/v1/upload/batch`          | Upload multiple resumes  |
| GET    | `/api/v1/upload/{id}/status`    | Check processing status  |
| GET    | `/api/v1/upload/`               | List all resumes         |
| DELETE | `/api/v1/upload/{id}`           | Delete a resume          |
| POST   | `/api/v1/extract/{id}`          | Trigger extraction       |
| GET    | `/api/v1/extract/{id}/result`   | Get extraction result    |
| POST   | `/api/v1/extract/bulk`          | Bulk extract             |
| POST   | `/api/v1/export/`               | Generate Excel/CSV       |
| GET    | `/api/v1/export/download/{file}`| Download export file     |
| GET    | `/api/v1/export/stream/csv`     | Stream CSV response      |
| GET    | `/api/v1/export/{id}/excel`     | Export single to Excel   |
| GET    | `/health`                       | Health check             |

---

## 🧪 Running Tests

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run unit tests only
pytest tests/unit/ -v

# Run integration tests only
pytest tests/integration/ -v
```

---

## 📁 Project Structure

```
resume_extractor/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Settings & env vars
│   ├── api/                 # Routes & middleware
│   ├── core/                # PDF parsing & pipeline
│   ├── extraction/          # Field extractors
│   ├── nlp/                 # NLP utilities
│   ├── matching/            # Skill & title normalization
│   ├── validation/          # Schema validation
│   ├── export/              # Excel & CSV generation
│   ├── database/            # DB connection & repos
│   ├── models/              # ORM models & schemas
│   └── storage/             # File handling
├── tests/                   # Unit & integration tests
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and configure:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/resume_db
APP_ENV=development
DEBUG=True
OCR_USE_GPU=False
SKILLS_FUZZY_THRESHOLD=80
MAX_UPLOAD_SIZE_MB=10
```

---

## 📊 Extraction Output

```json
{
  "contact": {
    "full_name": "John Smith",
    "email": "john@example.com",
    "phone": "+1 555-123-4567",
    "linkedin": "https://linkedin.com/in/johnsmith"
  },
  "experience": [{
    "job_title": "Senior Software Engineer",
    "company": "Google",
    "start_date": "Jan 2021",
    "end_date": "Present",
    "is_current": true,
    "duration_years": 3.5
  }],
  "education": [{
    "degree": "Bachelor of Science",
    "field_of_study": "Computer Science",
    "institution": "MIT",
    "graduation_date": "Jun 2018",
    "gpa": "3.8/4.0"
  }],
  "skills": {
    "all": ["Python", "Django", "Docker", "AWS"],
    "programming_languages": ["Python"],
    "frameworks": ["Django"],
    "cloud_devops": ["Docker", "AWS"]
  },
  "confidence_scores": {
    "overall": 0.87,
    "contact": 0.95,
    "experience": 0.82
  }
}
```
