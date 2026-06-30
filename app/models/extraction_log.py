# app/models/extraction_log.py

import uuid
from sqlalchemy import (
    Column, String, Float, Integer,
    DateTime, Text, Boolean,
    ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.connection import Base


class ExtractionLog(Base):
    """
    Audit log for every extraction attempt on a resume.
    Tracks what was extracted, confidence scores, and any warnings.
    Useful for debugging layout issues and improving accuracy over time.
    """
    __tablename__ = "extraction_logs"

    # ─── Primary Key ───────────────────────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # ─── Foreign Key ───────────────────────────────────────────────────────────
    resume_id = Column(
        UUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume = relationship("Resume", back_populates="extraction_logs")

    # ─── Pipeline Stage ────────────────────────────────────────────────────────
    stage = Column(
        String(100),
        nullable=False,
        comment="Pipeline stage: pdf_detection, ocr, layout, extraction, validation",
    )
    stage_order = Column(Integer, nullable=True)

    # ─── Outcome ───────────────────────────────────────────────────────────────
    success       = Column(Boolean, default=True, nullable=False)
    error_type    = Column(String(100), nullable=True)
    error_message = Column(Text,        nullable=True)
    warning_count = Column(Integer,     default=0)
    warnings      = Column(JSONB,       nullable=True)   # List of warning strings

    # ─── Performance ───────────────────────────────────────────────────────────
    duration_seconds = Column(Float,   nullable=True)
    memory_mb        = Column(Float,   nullable=True)

    # ─── Extraction Details ────────────────────────────────────────────────────
    sections_detected    = Column(JSONB,   nullable=True)   # List of detected section names
    fields_extracted     = Column(Integer, default=0)
    fields_failed        = Column(Integer, default=0)
    confidence_scores    = Column(JSONB,   nullable=True)   # Per-field confidence
    overall_confidence   = Column(Float,   nullable=True)

    # ─── Parser Info ───────────────────────────────────────────────────────────
    parser_used          = Column(String(50),  nullable=True)   # 'pymupdf', 'paddleocr'
    layout_analyzer_used = Column(String(50),  nullable=True)   # 'pp_structure', 'layoutparser'
    spacy_model_used     = Column(String(50),  nullable=True)
    extraction_version   = Column(String(20),  nullable=True)

    # ─── Input Metadata ────────────────────────────────────────────────────────
    page_count           = Column(Integer, nullable=True)
    text_length          = Column(Integer, nullable=True)
    detected_language    = Column(String(10), nullable=True)
    is_multicolumn       = Column(Boolean, nullable=True)

    # ─── Timestamps ────────────────────────────────────────────────────────────
    started_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # ─── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_extraction_logs_resume_id", "resume_id"),
        Index("ix_extraction_logs_stage",     "stage"),
        Index("ix_extraction_logs_success",   "success"),
        Index("ix_extraction_logs_started_at","started_at"),
    )

    # ─── Repr ──────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<ExtractionLog id={self.id} "
            f"resume_id={self.resume_id} "
            f"stage='{self.stage}' "
            f"success={self.success}>"
        )

    # ─── Properties ────────────────────────────────────────────────────────────
    @property
    def has_errors(self) -> bool:
        return not self.success

    @property
    def has_warnings(self) -> bool:
        return (self.warning_count or 0) > 0

    @property
    def extraction_rate(self) -> float | None:
        """Percentage of fields successfully extracted."""
        total = (self.fields_extracted or 0) + (self.fields_failed or 0)
        if total == 0:
            return None
        return round((self.fields_extracted / total) * 100, 1)
