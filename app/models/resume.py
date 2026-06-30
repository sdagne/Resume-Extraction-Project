# app/models/resume.py

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float,
    DateTime, Boolean, Text, Enum as SAEnum,
    ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.connection import Base
from app.utils.constants import PDFType


class Resume(Base):
    """
    Stores uploaded resume file metadata and processing status.
    One resume belongs to one candidate.
    """
    __tablename__ = "resumes"

    # ─── Primary Key ───────────────────────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        index=True,
    )

    # ─── File Info ─────────────────────────────────────────────────────────────
    original_filename = Column(String(255), nullable=False)
    stored_filename   = Column(String(255), nullable=False, unique=True)
    file_path         = Column(String(512), nullable=False)
    file_size_bytes   = Column(Integer, nullable=True)
    file_hash         = Column(String(64),  nullable=True, index=True)
    file_extension    = Column(String(10),  nullable=True)

    # ─── PDF Classification ────────────────────────────────────────────────────
    pdf_type = Column(
        SAEnum(PDFType.DIGITAL, PDFType.SCANNED, PDFType.MIXED, name="pdf_type_enum"),
        nullable=True,
    )
    page_count    = Column(Integer, nullable=True)
    has_tables    = Column(Boolean, default=False)
    has_images    = Column(Boolean, default=False)
    is_multicolumn= Column(Boolean, default=False)

    # ─── Processing Status ─────────────────────────────────────────────────────
    status = Column(
        SAEnum(
            "pending", "processing", "completed", "failed", "skipped",
            name="resume_status_enum"
        ),
        default="pending",
        nullable=False,
        index=True,
    )
    error_message       = Column(Text, nullable=True)
    processing_duration = Column(Float, nullable=True)   # seconds
    retry_count         = Column(Integer, default=0)

    # ─── Raw Extracted Text ────────────────────────────────────────────────────
    raw_text            = Column(Text, nullable=True)
    raw_text_length     = Column(Integer, nullable=True)

    # ─── Extracted JSON ────────────────────────────────────────────────────────
    extracted_data      = Column(JSONB, nullable=True)   # Full structured JSON
    extraction_version  = Column(String(20), nullable=True, default="1.0.0")

    # ─── Confidence Scores ─────────────────────────────────────────────────────
    overall_confidence  = Column(Float, nullable=True)   # 0.0 – 1.0
    field_confidences   = Column(JSONB, nullable=True)   # Per-field scores

    # ─── Relationships ─────────────────────────────────────────────────────────
    candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    candidate       = relationship("Candidate", back_populates="resumes")
    extraction_logs = relationship(
        "ExtractionLog",
        back_populates="resume",
        cascade="all, delete-orphan",
    )

    # ─── Timestamps ────────────────────────────────────────────────────────────
    uploaded_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at  = Column(DateTime(timezone=True), nullable=True)
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # ─── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_resumes_status_uploaded", "status", "uploaded_at"),
        Index("ix_resumes_file_hash",       "file_hash"),
    )

    # ─── Repr ──────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<Resume id={self.id} "
            f"file='{self.original_filename}' "
            f"status='{self.status}'>"
        )

    # ─── Properties ────────────────────────────────────────────────────────────
    @property
    def is_processed(self) -> bool:
        return self.status == "completed"

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"

    @property
    def file_size_kb(self) -> float | None:
        if self.file_size_bytes:
            return round(self.file_size_bytes / 1024, 2)
        return None

    def mark_processing(self) -> None:
        self.status = "processing"
        self.updated_at = datetime.utcnow()

    def mark_completed(
        self,
        extracted_data: dict,
        duration: float,
        confidence: float,
    ) -> None:
        self.status              = "completed"
        self.extracted_data      = extracted_data
        self.processing_duration = duration
        self.overall_confidence  = confidence
        self.processed_at        = datetime.utcnow()
        self.updated_at          = datetime.utcnow()

    def mark_failed(self, error: str) -> None:
        self.status        = "failed"
        self.error_message = error
        self.retry_count   = (self.retry_count or 0) + 1
        self.updated_at    = datetime.utcnow()
