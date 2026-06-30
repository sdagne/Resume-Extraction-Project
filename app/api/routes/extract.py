# app/api/routes/extract.py

import time
from typing import Optional

from fastapi import APIRouter, Depends, BackgroundTasks, status
from sqlalchemy.orm import Session

from app.utils.logger import get_logger
from app.database.connection import get_db
from app.database.resume_repository import ResumeRepository
from app.core.pipeline import extraction_pipeline
from app.api.middleware.error_handler import (
    FileNotFoundException,
    ExtractionException,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/extract", tags=["Extraction"])


# ─── Response Models ───────────────────────────────────────────────────────────
from pydantic import BaseModel, ConfigDict
from typing import Any
from uuid import UUID
from datetime import datetime


class ExtractionResult(BaseModel):
    """Full extraction result for a single resume."""
    resume_id:          UUID
    status:             str
    extracted_data:     Optional[dict]   = None
    overall_confidence: Optional[float]  = None
    processing_duration:Optional[float]  = None
    warnings:           list[str]        = []
    sections_detected:  list[str]        = []
    processed_at:       Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ReExtractRequest(BaseModel):
    """Request body for re-extraction."""
    force:   bool = False   # Force re-extraction even if already completed
    resume_id: UUID


class BulkExtractRequest(BaseModel):
    """Request body for bulk extraction trigger."""
    resume_ids: Optional[list[UUID]] = None   # None = extract all pending
    force:      bool = False


class BulkExtractResponse(BaseModel):
    """Response for bulk extraction trigger."""
    queued:   int
    skipped:  int
    failed:   int
    message:  str


# ─── Routes ────────────────────────────────────────────────────────────────────
@router.post(
    "/{resume_id}",
    response_model=ExtractionResult,
    summary="Extract a specific resume",
    description=(
        "Trigger synchronous extraction for a specific resume. "
        "Use this for immediate results on individual resumes."
    ),
)
async def extract_resume(
    resume_id: str,
    force:     bool = False,
    db: Session = Depends(get_db),
) -> ExtractionResult:
    """
    Synchronously extract a specific resume.

    Args:
        resume_id: UUID of the uploaded resume
        force:     Re-extract even if already completed
    """
    repo   = ResumeRepository(db)
    resume = repo.get_by_id(resume_id)

    if not resume:
        raise FileNotFoundException("Resume", resume_id)

    # Skip if already completed (unless forced)
    if resume.status == "completed" and not force:
        return ExtractionResult(
            resume_id           = resume.id,
            status              = resume.status,
            extracted_data      = resume.extracted_data,
            overall_confidence  = resume.overall_confidence,
            processing_duration = resume.processing_duration,
            warnings            = resume.extracted_data.get(
                "extraction_warnings", []
            ) if resume.extracted_data else [],
            sections_detected   = resume.extracted_data.get(
                "sections_detected", []
            ) if resume.extracted_data else [],
            processed_at        = resume.processed_at,
        )

    # Mark as processing
    repo.mark_as_processing(resume_id)

    # Run pipeline synchronously
    try:
        start  = time.time()
        result = extraction_pipeline.run(
            file_path = resume.file_path,
            resume_id = resume.id,
        )

        schema     = result["schema"]
        pdf_meta   = result["pdf_metadata"]
        duration   = round(time.time() - start, 2)
        confidence = result["overall_confidence"]

        # Serialize schema
        extracted_data = schema.model_dump()

        # Update DB
        repo.mark_as_completed(
            resume_id      = resume_id,
            extracted_data = extracted_data,
            duration       = duration,
            confidence     = confidence,
        )

        # Update PDF metadata
        repo.update(resume_id, {
            "pdf_type":       pdf_meta.get("pdf_type"),
            "page_count":     pdf_meta.get("page_count"),
            "is_multicolumn": pdf_meta.get("is_multicolumn"),
        })

        # Upsert candidate
        from app.database.resume_repository import CandidateRepository
        candidate_repo = CandidateRepository(db)
        candidate      = candidate_repo.upsert_from_extraction(
            extracted_data, resume.id
        )
        repo.update(resume_id, {"candidate_id": str(candidate.id)})

        logger.info(
            f"Synchronous extraction complete: "
            f"resume_id={resume_id} | "
            f"confidence={confidence:.3f} | "
            f"duration={duration}s"
        )

        return ExtractionResult(
            resume_id           = resume.id,
            status              = "completed",
            extracted_data      = extracted_data,
            overall_confidence  = confidence,
            processing_duration = duration,
            warnings            = result.get("warnings", []),
            sections_detected   = extracted_data.get("sections_detected", []),
            processed_at        = resume.processed_at,
        )

    except Exception as e:
        error_msg = str(e)
        repo.mark_as_failed(resume_id, error_msg)
        logger.error(
            f"Synchronous extraction failed: "
            f"resume_id={resume_id} | error={error_msg}"
        )
        raise ExtractionException(
            message   = f"Extraction failed: {error_msg}",
            resume_id = resume_id,
        )


@router.get(
    "/{resume_id}/result",
    response_model=ExtractionResult,
    summary="Get extraction result",
    description="Retrieve the full extraction result for a completed resume.",
)
async def get_extraction_result(
    resume_id: str,
    db: Session = Depends(get_db),
) -> ExtractionResult:
    """Get the extraction result for a specific resume."""
    repo   = ResumeRepository(db)
    resume = repo.get_by_id(resume_id)

    if not resume:
        raise FileNotFoundException("Resume", resume_id)

    if resume.status != "completed":
        return ExtractionResult(
            resume_id  = resume.id,
            status     = resume.status,
            warnings   = (
                [resume.error_message]
                if resume.error_message else []
            ),
        )

    return ExtractionResult(
        resume_id           = resume.id,
        status              = resume.status,
        extracted_data      = resume.extracted_data,
        overall_confidence  = resume.overall_confidence,
        processing_duration = resume.processing_duration,
        warnings            = resume.extracted_data.get(
            "extraction_warnings", []
        ) if resume.extracted_data else [],
        sections_detected   = resume.extracted_data.get(
            "sections_detected", []
        ) if resume.extracted_data else [],
        processed_at        = resume.processed_at,
    )


@router.post(
    "/bulk",
    response_model=BulkExtractResponse,
    summary="Trigger bulk extraction",
    description=(
        "Queue extraction for multiple resumes. "
        "If no IDs provided, processes all pending resumes."
    ),
)
async def bulk_extract(
    request:          BulkExtractRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> BulkExtractResponse:
    """
    Trigger bulk extraction as background tasks.
    """
    repo    = ResumeRepository(db)
    queued  = 0
    skipped = 0
    failed  = 0

    # Get resumes to process
    if request.resume_ids:
        resumes = [
            repo.get_by_id(str(rid))
            for rid in request.resume_ids
        ]
        resumes = [r for r in resumes if r]
    else:
        resumes = repo.get_pending_resumes(limit=100)

    for resume in resumes:
        try:
            # Skip completed unless forced
            if resume.status == "completed" and not request.force:
                skipped += 1
                continue

            from app.api.routes.upload import _extract_resume_background
            background_tasks.add_task(
                _extract_resume_background,
                resume_id = str(resume.id),
                file_path = resume.file_path,
            )
            queued += 1

        except Exception as e:
            logger.error(
                f"Failed to queue resume {resume.id}: {e}"
            )
            failed += 1

    logger.info(
        f"Bulk extraction queued: "
        f"queued={queued}, skipped={skipped}, failed={failed}"
    )

    return BulkExtractResponse(
        queued  = queued,
        skipped = skipped,
        failed  = failed,
        message = (
            f"Queued {queued} resumes for extraction. "
            f"Skipped {skipped} (already completed). "
            f"Failed to queue: {failed}."
        ),
    )


@router.post(
    "/retry-failed",
    response_model=BulkExtractResponse,
    summary="Retry failed extractions",
)
async def retry_failed(
    background_tasks: BackgroundTasks,
    max_retries: int = 3,
    db: Session = Depends(get_db),
) -> BulkExtractResponse:
    """Retry all failed resumes that haven't exceeded max_retries."""
    repo    = ResumeRepository(db)
    failed  = repo.get_failed_resumes(max_retries=max_retries)
    queued  = 0

    for resume in failed:
        from app.api.routes.upload import _extract_resume_background
        background_tasks.add_task(
            _extract_resume_background,
            resume_id = str(resume.id),
            file_path = resume.file_path,
        )
        queued += 1

    return BulkExtractResponse(
        queued  = queued,
        skipped = 0,
        failed  = 0,
        message = f"Queued {queued} failed resumes for retry",
    )
