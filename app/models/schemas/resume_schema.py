# Pydantic input/output schemas
# app/models/schemas/resume_schema.py

from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


# ─── Upload ────────────────────────────────────────────────────────────────────
class ResumeUploadResponse(BaseModel):
    """Response returned after a successful resume upload."""
    resume_id:         UUID
    original_filename: str
    file_size_kb:      float
    status:            str
    message:           str

    model_config = ConfigDict(from_attributes=True)


# ─── Status ────────────────────────────────────────────────────────────────────
class ResumeStatusResponse(BaseModel):
    """Response for checking the processing status of a resume."""
    resume_id:           UUID
    status:              str
    pdf_type:            Optional[str]   = None
    page_count:          Optional[int]   = None
    overall_confidence:  Optional[float] = None
    processing_duration: Optional[float] = None
    error_message:       Optional[str]   = None
    uploaded_at:         datetime
    processed_at:        Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Summary ───────────────────────────────────────────────────────────────────
class ResumeSummary(BaseModel):
    """Lightweight summary of a resume record for list views."""
    resume_id:          UUID
    original_filename:  str
    status:             str
    overall_confidence: Optional[float]    = None
    candidate_name:     Optional[str]      = None
    candidate_email:    Optional[str]      = None
    uploaded_at:        datetime

    model_config = ConfigDict(from_attributes=True)


# ─── List Response ─────────────────────────────────────────────────────────────
class ResumeListResponse(BaseModel):
    """Paginated list of resume summaries."""
    items:      list[ResumeSummary]
    total:      int
    page:       int
    page_size:  int
    has_next:   bool


# ─── Export Request ────────────────────────────────────────────────────────────
class ExportRequest(BaseModel):
    """Request body for exporting extracted data."""
    resume_ids:    Optional[list[UUID]] = Field(
        default=None,
        description="Specific resume IDs to export. If None, exports all completed."
    )
    format:        str = Field(
        default="excel",
        pattern="^(excel|csv)$",
        description="Export format: 'excel' or 'csv'"
    )
    include_raw:   bool = Field(
        default=False,
        description="Include raw extracted text in export"
    )
    date_from:     Optional[datetime] = None
    date_to:       Optional[datetime] = None

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        return v.lower()


# ─── Export Response ───────────────────────────────────────────────────────────
class ExportResponse(BaseModel):
    """Response after triggering an export."""
    export_id:    str
    filename:     str
    download_url: str
    record_count: int
    format:       str
    created_at:   datetime


# ─── Statistics ────────────────────────────────────────────────────────────────
class ProcessingStats(BaseModel):
    """Overall processing statistics."""
    total_uploaded:  int
    total_completed: int
    total_failed:    int
    total_pending:   int
    avg_confidence:  float
    avg_duration_s:  float
