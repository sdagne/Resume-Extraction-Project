# app/database/resume_repository.py

from typing import Optional, List
from uuid import UUID
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import select, and_, desc

from app.database.repository import BaseRepository
from app.models.resume import Resume
from app.models.candidate import Candidate
from app.models.extraction_log import ExtractionLog
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ResumeRepository(BaseRepository[Resume]):
    """
    Resume-specific database operations extending the generic BaseRepository.
    """

    def __init__(self, db: Session):
        super().__init__(Resume, db)

    # ─── Resume-Specific Queries ───────────────────────────────────────────────

    def get_by_file_hash(self, file_hash: str) -> Optional[Resume]:
        """Find a resume by its file content hash (deduplication)."""
        return self.get_by_field("file_hash", file_hash, first_only=True)

    def get_by_status(
        self,
        status: str,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Resume]:
        """Get all resumes with a specific processing status."""
        stmt = (
            select(Resume)
            .where(Resume.status == status)
            .order_by(desc(Resume.uploaded_at))
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_pending_resumes(self, limit: int = 10) -> List[Resume]:
        """Fetch unprocessed resumes ordered by upload time."""
        return self.get_by_status("pending", limit=limit)

    def get_failed_resumes(self, max_retries: int = 3) -> List[Resume]:
        """Fetch failed resumes that haven't exceeded retry limit."""
        stmt = (
            select(Resume)
            .where(
                and_(
                    Resume.status == "failed",
                    Resume.retry_count < max_retries,
                )
            )
            .order_by(Resume.uploaded_at)
        )
        return list(self.db.scalars(stmt).all())

    def get_resumes_with_candidate(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Resume]:
        """Fetch resumes with their associated candidate (eager load)."""
        stmt = (
            select(Resume)
            .join(Candidate, Resume.candidate_id == Candidate.id, isouter=True)
            .order_by(desc(Resume.uploaded_at))
            .offset(skip)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def mark_as_processing(self, resume_id: UUID) -> Optional[Resume]:
        """Set resume status to processing."""
        resume = self.get_by_id(resume_id)
        if resume:
            resume.mark_processing()
            self.db.flush()
        return resume

    def mark_as_completed(
        self,
        resume_id: UUID,
        extracted_data: dict,
        duration: float,
        confidence: float,
    ) -> Optional[Resume]:
        """Mark resume as successfully processed with extracted data."""
        resume = self.get_by_id(resume_id)
        if resume:
            resume.mark_completed(extracted_data, duration, confidence)
            self.db.flush()
        return resume

    def mark_as_failed(
        self,
        resume_id: UUID,
        error_message: str,
    ) -> Optional[Resume]:
        """Mark resume as failed with error details."""
        resume = self.get_by_id(resume_id)
        if resume:
            resume.mark_failed(error_message)
            self.db.flush()
        return resume

    def get_statistics(self) -> dict:
        """Return processing statistics summary."""
        from sqlalchemy import func
        stats = (
            self.db.query(
                Resume.status,
                func.count(Resume.id).label("count"),
                func.avg(Resume.overall_confidence).label("avg_confidence"),
                func.avg(Resume.processing_duration).label("avg_duration"),
            )
            .group_by(Resume.status)
            .all()
        )
        return {
            row.status: {
                "count":          row.count,
                "avg_confidence": round(float(row.avg_confidence or 0), 3),
                "avg_duration":   round(float(row.avg_duration   or 0), 2),
            }
            for row in stats
        }


class CandidateRepository(BaseRepository[Candidate]):
    """
    Candidate-specific database operations.
    """

    def __init__(self, db: Session):
        super().__init__(Candidate, db)

    def get_by_email(self, email: str) -> Optional[Candidate]:
        """Find a candidate by email address."""
        return self.get_by_field("email", email.lower().strip(), first_only=True)

    def search_by_name(self, name: str, limit: int = 20) -> List[Candidate]:
        """Search candidates by partial name match."""
        stmt = (
            select(Candidate)
            .where(Candidate.full_name.ilike(f"%{name}%"))
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all())

    def get_by_skills(self, skills: List[str], limit: int = 50) -> List[Candidate]:
        """Find candidates who have ALL the given skills."""
        stmt = select(Candidate)
        for skill in skills:
            stmt = stmt.where(
                Candidate.skills_normalized.contains([skill])
            )
        stmt = stmt.limit(limit)
        return list(self.db.scalars(stmt).all())

    def upsert_from_extraction(
        self,
        extracted_data: dict,
        resume_id: UUID,
    ) -> Candidate:
        """
        Create or update a candidate from extracted resume data.
        Matches on email if available, otherwise creates new record.
        """
        email = extracted_data.get("contact", {}).get("email")

        # Try to find existing candidate by email
        existing = self.get_by_email(email) if email else None

        candidate_data = self._map_extracted_to_candidate(extracted_data)
        candidate_data["source"] = "upload"

        if existing:
            logger.info(f"Updating existing candidate: {existing.id}")
            return self.update_instance(existing, candidate_data)
        else:
            logger.info("Creating new candidate from extraction")
            return self.create(candidate_data)

    def _map_extracted_to_candidate(self, data: dict) -> dict:
        """Map extracted JSON structure to Candidate model fields."""
        contact     = data.get("contact",     {})
        experience  = data.get("experience",  [])
        education   = data.get("education",   [])
        skills_data = data.get("skills",      {})

        # Calculate total experience
        total_years = sum(
            exp.get("duration_years", 0) or 0
            for exp in experience
        )

        # Get latest job
        current_jobs = [e for e in experience if e.get("is_current")]
        latest_job   = current_jobs[0] if current_jobs else (experience[0] if experience else {})

        # Get highest degree
        highest_degree = education[0].get("degree") if education else None

        # Flatten all skills
        all_skills = []
        if isinstance(skills_data, dict):
            for skill_list in skills_data.values():
                if isinstance(skill_list, list):
                    all_skills.extend(skill_list)
        elif isinstance(skills_data, list):
            all_skills = skills_data

        return {
            "full_name":              contact.get("full_name"),
            "email":                  contact.get("email"),
            "phone":                  contact.get("phone"),
            "address":                contact.get("address"),
            "city":                   contact.get("city"),
            "country":                contact.get("country"),
            "linkedin_url":           contact.get("linkedin"),
            "github_url":             contact.get("github"),
            "website_url":            contact.get("website"),
            "summary":                data.get("summary"),
            "total_experience_years": round(total_years, 1),
            "latest_job_title":       latest_job.get("job_title"),
            "latest_company":         latest_job.get("company"),
            "experience":             experience,
            "highest_degree":         highest_degree,
            "education":              education,
            "skills":                 all_skills,
            "skills_json":            skills_data if isinstance(skills_data, dict) else {"all": all_skills},
            "certifications":         data.get("certifications", []),
            "projects":               data.get("projects",       []),
            "languages":              data.get("languages",      []),
            "awards":                 data.get("awards",         []),
            "resume_language":        data.get("detected_language"),
        }


class ExtractionLogRepository(BaseRepository[ExtractionLog]):
    """
    Extraction log-specific database operations.
    """

    def __init__(self, db: Session):
        super().__init__(ExtractionLog, db)

    def get_by_resume(self, resume_id: UUID) -> List[ExtractionLog]:
        """Get all log entries for a specific resume."""
        stmt = (
            select(ExtractionLog)
            .where(ExtractionLog.resume_id == resume_id)
            .order_by(ExtractionLog.started_at)
        )
        return list(self.db.scalars(stmt).all())

    def get_failed_stages(self, resume_id: UUID) -> List[ExtractionLog]:
        """Get all failed pipeline stages for a resume."""
        stmt = (
            select(ExtractionLog)
            .where(
                and_(
                    ExtractionLog.resume_id == resume_id,
                    ExtractionLog.success == False,
                )
            )
        )
        return list(self.db.scalars(stmt).all())

    def log_stage(
        self,
        resume_id: UUID,
        stage: str,
        stage_order: int,
        success: bool,
        duration: float,
        details: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> ExtractionLog:
        """Convenience method to create a stage log entry."""
        details = details or {}
        return self.create({
            "resume_id":          resume_id,
            "stage":              stage,
            "stage_order":        stage_order,
            "success":            success,
            "duration_seconds":   duration,
            "error_message":      error,
            "completed_at":       datetime.utcnow(),
            "fields_extracted":   details.get("fields_extracted", 0),
            "fields_failed":      details.get("fields_failed", 0),
            "overall_confidence": details.get("confidence"),
            "sections_detected":  details.get("sections_detected"),
            "parser_used":        details.get("parser_used"),
            "detected_language":  details.get("detected_language"),
            "is_multicolumn":     details.get("is_multicolumn"),
            "text_length":        details.get("text_length"),
            "page_count":         details.get("page_count"),
        })
