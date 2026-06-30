# app/models/candidate.py

import uuid
from sqlalchemy import (
    Column, String, Integer, Float,
    DateTime, Text, Boolean,
    Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.connection import Base


class Candidate(Base):
    """
    Stores the structured candidate profile extracted from resumes.
    One candidate can have multiple resumes (e.g., updated versions).
    """
    __tablename__ = "candidates"

    # ─── Primary Key ───────────────────────────────────────────────────────────
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        index=True,
    )

    # ─── Personal Information ──────────────────────────────────────────────────
    full_name    = Column(String(255), nullable=True, index=True)
    first_name   = Column(String(100), nullable=True)
    last_name    = Column(String(100), nullable=True)
    email        = Column(String(255), nullable=True, index=True)
    phone        = Column(String(50),  nullable=True)
    address      = Column(String(500), nullable=True)
    city         = Column(String(100), nullable=True)
    country      = Column(String(100), nullable=True)

    # ─── Online Profiles ───────────────────────────────────────────────────────
    linkedin_url = Column(String(500), nullable=True)
    github_url   = Column(String(500), nullable=True)
    website_url  = Column(String(500), nullable=True)

    # ─── Professional Summary ──────────────────────────────────────────────────
    summary      = Column(Text, nullable=True)

    # ─── Experience ────────────────────────────────────────────────────────────
    total_experience_years = Column(Float,       nullable=True)
    latest_job_title       = Column(String(255), nullable=True)
    latest_company         = Column(String(255), nullable=True)
    experience             = Column(JSONB,        nullable=True)
    # Structure: [
    #   {
    #     "job_title": str, "company": str,
    #     "start_date": str, "end_date": str,
    #     "duration_years": float, "is_current": bool,
    #     "description": str, "location": str
    #   }, ...
    # ]

    # ─── Education ─────────────────────────────────────────────────────────────
    highest_degree      = Column(String(100), nullable=True)
    education           = Column(JSONB,        nullable=True)
    # Structure: [
    #   {
    #     "degree": str, "field_of_study": str,
    #     "institution": str, "graduation_date": str,
    #     "gpa": str, "location": str
    #   }, ...
    # ]

    # ─── Skills ────────────────────────────────────────────────────────────────
    skills              = Column(ARRAY(String), nullable=True)
    skills_normalized   = Column(ARRAY(String), nullable=True)   # After taxonomy mapping
    skills_json         = Column(JSONB,          nullable=True)
    # Structure: {
    #   "technical": [...], "soft": [...], "tools": [...], "languages": [...]
    # }

    # ─── Certifications ────────────────────────────────────────────────────────
    certifications      = Column(JSONB, nullable=True)
    # Structure: [
    #   {"name": str, "issuer": str, "date": str, "expiry": str}
    # ]

    # ─── Projects ──────────────────────────────────────────────────────────────
    projects            = Column(JSONB, nullable=True)
    # Structure: [
    #   {"name": str, "description": str, "technologies": [...], "url": str}
    # ]

    # ─── Languages ─────────────────────────────────────────────────────────────
    languages           = Column(JSONB, nullable=True)
    # Structure: [{"language": str, "proficiency": str}]

    # ─── Awards ────────────────────────────────────────────────────────────────
    awards              = Column(JSONB, nullable=True)

    # ─── Meta ──────────────────────────────────────────────────────────────────
    resume_language     = Column(String(10),  nullable=True)   # e.g. 'en', 'de'
    is_active           = Column(Boolean, default=True)
    source              = Column(String(100), nullable=True)   # e.g. 'upload', 'api'

    # ─── Relationships ─────────────────────────────────────────────────────────
    resumes = relationship(
        "Resume",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )

    # ─── Timestamps ────────────────────────────────────────────────────────────
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # ─── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_candidates_full_name",  "full_name"),
        Index("ix_candidates_email",      "email"),
        Index("ix_candidates_created_at", "created_at"),
    )

    # ─── Repr ──────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<Candidate id={self.id} "
            f"name='{self.full_name}' "
            f"email='{self.email}'>"
        )

    # ─── Properties ────────────────────────────────────────────────────────────
    @property
    def display_name(self) -> str:
        return self.full_name or self.email or str(self.id)

    @property
    def skills_count(self) -> int:
        return len(self.skills) if self.skills else 0

    @property
    def experience_count(self) -> int:
        return len(self.experience) if self.experience else 0

    @property
    def has_complete_profile(self) -> bool:
        """Check if minimum required fields are populated."""
        return all([
            self.full_name,
            self.email or self.phone,
            self.experience or self.education,
        ])
