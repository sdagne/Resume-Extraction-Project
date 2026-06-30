# tests/conftest.py

import os
import pytest
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# ─── Test database (SQLite in-memory) ─────────────────────────────────────────
TEST_DATABASE_URL = "sqlite:///./test_resume.db"

# Override settings BEFORE importing app
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["APP_ENV"]      = "testing"
os.environ["DEBUG"]        = "True"
os.environ["USE_S3"]       = "False"
os.environ["OCR_USE_GPU"]  = "False"

from app.main import create_app
from app.database.connection import Base, get_db
from app.config import settings

# ─── Test Engine ───────────────────────────────────────────────────────────────
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def setup_test_db():
    """Create all tables for testing session."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    # Clean up test DB file
    test_db = Path("test_resume.db")
    if test_db.exists():
        test_db.unlink()


@pytest.fixture
def db(setup_test_db) -> Generator[Session, None, None]:
    """Provide a test database session that rolls back after each test."""
    connection  = test_engine.connect()
    transaction = connection.begin()
    session     = TestSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db) -> Generator[TestClient, None, None]:
    """Provide a FastAPI test client with DB override."""
    app = create_app()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_pdf_path() -> Path:
    """Path to a sample digital PDF for testing."""
    path = Path("tests/sample_resumes/digital_single_column.pdf")
    if not path.exists():
        pytest.skip(f"Sample PDF not found: {path}")
    return path


@pytest.fixture
def sample_scanned_pdf_path() -> Path:
    """Path to a sample scanned PDF for testing."""
    path = Path("tests/sample_resumes/scanned_resume.pdf")
    if not path.exists():
        pytest.skip(f"Sample scanned PDF not found: {path}")
    return path


@pytest.fixture
def sample_resume_text() -> str:
    """Sample resume text for unit testing."""
    return """
John Smith
Senior Software Engineer
john.smith@email.com | +1 (555) 123-4567
linkedin.com/in/johnsmith | github.com/johnsmith
New York, NY, USA

PROFESSIONAL SUMMARY
Experienced software engineer with 7+ years building scalable
backend systems and APIs. Passionate about clean code and
distributed systems.

WORK EXPERIENCE

Senior Software Engineer | Google | New York, NY
Jan 2021 - Present
- Led development of microservices architecture serving 10M+ users
- Reduced API latency by 40% through caching optimization
- Mentored team of 5 junior engineers

Software Engineer | Amazon | Seattle, WA
Mar 2018 - Dec 2020
- Built RESTful APIs using Python and Django
- Implemented CI/CD pipelines with Jenkins and Docker
- Collaborated with cross-functional teams on product features

EDUCATION

Bachelor of Science in Computer Science
Massachusetts Institute of Technology (MIT)
Sep 2014 - Jun 2018 | GPA: 3.8/4.0

SKILLS
Programming: Python, Java, Go, JavaScript, TypeScript
Frameworks: Django, FastAPI, Spring Boot, React, Node.js
Databases: PostgreSQL, MongoDB, Redis, Elasticsearch
Cloud & DevOps: AWS, Docker, Kubernetes, Terraform, CI/CD
Tools: Git, JIRA, Confluence, Postman

CERTIFICATIONS
AWS Certified Solutions Architect – Professional | Amazon | 2022
Google Cloud Professional Data Engineer | Google | 2021

PROJECTS
Distributed Task Queue System
Built a high-performance distributed task queue using Python and Redis.
Technologies: Python, Redis, Docker, Kubernetes
GitHub: github.com/johnsmith/task-queue
    """


@pytest.fixture
def sample_contact_text() -> str:
    """Sample contact section text."""
    return """
John Smith
john.smith@example.com
+1 (555) 123-4567
linkedin.com/in/johnsmith
github.com/johnsmith
New York, NY, USA
    """


@pytest.fixture
def sample_experience_text() -> str:
    """Sample experience section text."""
    return """
Senior Software Engineer | Google | New York, NY
Jan 2021 - Present
- Led development of microservices architecture
- Reduced API latency by 40%

Software Engineer | Amazon | Seattle, WA
Mar 2018 - Dec 2020
- Built RESTful APIs using Python and Django
- Implemented CI/CD pipelines
    """


@pytest.fixture
def sample_education_text() -> str:
    """Sample education section text."""
    return """
Bachelor of Science in Computer Science
Massachusetts Institute of Technology (MIT)
Sep 2014 - Jun 2018
GPA: 3.8/4.0
    """


@pytest.fixture
def sample_skills_text() -> str:
    """Sample skills section text."""
    return """
Programming Languages: Python, Java, Go, JavaScript, TypeScript
Frameworks: Django, FastAPI, Spring Boot, React, Node.js
Databases: PostgreSQL, MongoDB, Redis, Elasticsearch
Cloud & DevOps: AWS, Docker, Kubernetes, Terraform
Tools: Git, JIRA, Confluence
    """


@pytest.fixture
def mock_file_handler():
    """Mock file handler for upload tests."""
    mock = MagicMock()
    mock.save.return_value = {
        "stored_filename": "test_resume_abc123.pdf",
        "file_path":       "/tmp/test_resume_abc123.pdf",
        "file_size_bytes": 102400,
        "file_hash":       "abc123def456",
    }
    mock.delete.return_value = True
    mock.exists.return_value = True
    return mock
