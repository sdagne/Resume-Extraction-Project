# app/config.py

import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


# ─── Base Directory ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """
    Central configuration for the Resume Extractor application.
    All values can be overridden via environment variables or .env file.
    """

    # ─── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "Resume Extractor API"
    APP_VERSION: str = "1.0.0"
    APP_ENV: str = Field(default="development", env="APP_ENV")
    DEBUG: bool = Field(default=True, env="DEBUG")
    API_PREFIX: str = "/api/v1"

    # ─── Server ────────────────────────────────────────────────────────────────
    HOST: str = Field(default="0.0.0.0", env="HOST")
    PORT: int = Field(default=8000, env="PORT")

    # ─── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="postgresql://postgres:password@localhost:5432/resume_db",
        env="DATABASE_URL"
    )
    DB_POOL_SIZE: int = Field(default=5, env="DB_POOL_SIZE")
    DB_MAX_OVERFLOW: int = Field(default=10, env="DB_MAX_OVERFLOW")
    DB_ECHO: bool = Field(default=False, env="DB_ECHO")

    # ─── File Upload ───────────────────────────────────────────────────────────
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    EXPORT_DIR: Path = BASE_DIR / "exports"
    TEMP_DIR: Path = BASE_DIR / "temp"
    MAX_UPLOAD_SIZE_MB: int = Field(default=10, env="MAX_UPLOAD_SIZE_MB")
    ALLOWED_EXTENSIONS: list[str] = [".pdf", ".docx", ".doc"]

    # ─── OCR ───────────────────────────────────────────────────────────────────
    OCR_LANGUAGE: str = Field(default="en", env="OCR_LANGUAGE")
    OCR_USE_GPU: bool = Field(default=False, env="OCR_USE_GPU")
    OCR_CONFIDENCE_THRESHOLD: float = Field(default=0.75, env="OCR_CONFIDENCE_THRESHOLD")

    # ─── NLP ───────────────────────────────────────────────────────────────────
    SPACY_MODEL: str = Field(default="en_core_web_md", env="SPACY_MODEL")
    MIN_SECTION_CONFIDENCE: float = Field(default=0.6, env="MIN_SECTION_CONFIDENCE")

    # ─── Skills Matching ───────────────────────────────────────────────────────
    SKILLS_FUZZY_THRESHOLD: int = Field(default=80, env="SKILLS_FUZZY_THRESHOLD")
    TAXONOMY_DIR: Path = BASE_DIR / "app" / "matching" / "taxonomy"

    # ─── Storage (AWS S3 — optional) ───────────────────────────────────────────
    USE_S3: bool = Field(default=False, env="USE_S3")
    AWS_ACCESS_KEY_ID: str = Field(default="", env="AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: str = Field(default="", env="AWS_SECRET_ACCESS_KEY")
    AWS_REGION: str = Field(default="eu-central-1", env="AWS_REGION")
    S3_BUCKET_NAME: str = Field(default="resume-extractor", env="S3_BUCKET_NAME")

    # ─── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_DIR: Path = BASE_DIR / "logs"
    LOG_ROTATION: str = "10 MB"
    LOG_RETENTION: str = "30 days"

    # ─── Export ────────────────────────────────────────────────────────────────
    EXCEL_SHEET_NAME: str = "Extracted Resumes"
    CSV_DELIMITER: str = ","
    EXPORT_DATE_FORMAT: str = "%Y-%m-%d"

    # ─── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = Field(default="change-me-in-production", env="SECRET_KEY")
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        env="CORS_ORIGINS"
    )

    # ─── Enterprise Features ───────────────────────────────────────────────────
    DOCEX_RESUME_ENHANCE: bool = Field(default=False, env="DOCEX_RESUME_ENHANCE")
    DOCEX_RESUME_LAYOUT: bool = Field(default=False, env="DOCEX_RESUME_LAYOUT")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    # ─── Derived Properties ────────────────────────────────────────────────────
    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV.lower() == "development"

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist."""
        for directory in [
            self.UPLOAD_DIR,
            self.EXPORT_DIR,
            self.TEMP_DIR,
            self.LOG_DIR,
            self.TAXONOMY_DIR,
        ]:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                # Log to console if possible, but logger might not be ready
                print(f"Warning: Could not create directory {directory}: {e}")


# ─── Singleton Instance ────────────────────────────────────────────────────────
settings = Settings()
settings.ensure_directories()
