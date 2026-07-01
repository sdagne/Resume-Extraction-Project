# app/api/routes/upload.py

import time
from pathlib import Path
from typing import List

from fastapi import (
    APIRouter, Depends, File, UploadFile,
    HTTPException, status, BackgroundTasks,
)
from sqlalchemy.orm import Session

from app.config import settings
from app.utils.logger import get_logger
from app.utils.helpers import (
    get_file_extension,
    generate_file_hash,
    generate_uuid,
)
from app.database.connection import get_db
from app.database.resume_repository import ResumeRepository
from app.models.schemas.resume_schema import (
    ResumeUploadResponse,
    ResumeStatusResponse,
    ResumeListResponse,
    ResumeSummary,
    ProcessingStats,
)
from app.storage.file_handler import file_handler
from app.api.middleware.error_handler import (
    FileUploadException,
    FileNotFoundException,
)
from app.security.upload_security import upload_security
from app.security.api_key import require_api_key
from app.security.audit_logger import log_upload, log_security_event
from app.security.rate_limiter import limiter
from fastapi import Request

logger = get_logger(__name__)
router = APIRouter(prefix="/upload", tags=["Upload"])


# ─── Helpers ───────────────────────────────────────────────────────────────────
def _validate_upload_file(file: UploadFile) -> None:
    """Validate uploaded file type and size."""
    # Check extension
    ext = get_file_extension(file.filename or "")
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise FileUploadException(
            message = f"File type '{ext}' not allowed. "
                      f"Allowed: {settings.ALLOWED_EXTENSIONS}",
            details = {"filename": file.filename, "extension": ext},
        )

    # Check content type
    allowed_content_types = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document",
        "application/msword",
        "application/octet-stream",   # Some browsers send this
    }
    if (
        file.content_type
        and file.content_type not in allowed_content_types
    ):
        logger.warning(
            f"Unusual content type: {file.content_type} "
            f"for file {file.filename}"
        )


# ─── Routes ────────────────────────────────────────────────────────────────────
@router.post(
    "/",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a single resume",
    description=(
        "Upload a single PDF resume file. "
        "Returns a resume_id to track processing status."
    ),
)
async def upload_resume(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(
        ...,
        description="PDF resume file (max 10MB)",
    ),
    db: Session = Depends(get_db),
) -> ResumeUploadResponse:
    """
    Upload a single resume file.

    - Validates file type and size
    - Checks for duplicate (by file hash)
    - Saves file to storage
    - Creates DB record
    - Queues extraction as background task
    """
    # ── Validate ──────────────────────────────────────────────────────────────
    _validate_upload_file(file)

    # Read file content for hash check
    content = await file.read()
    await file.seek(0)   # Reset for saving
    # Audit log the upload event
    log_upload(
        client_ip=request.client.host if request.client else "unknown",
        filename=file.filename or "unknown",
        size_bytes=len(content),
        api_key_hint=api_key,
    )
    # Check file size
    if len(content) > settings.max_upload_size_bytes:
        raise FileUploadException(
            message = f"File too large. Max size: {settings.MAX_UPLOAD_SIZE_MB}MB",
            details = {
                "size_mb": round(len(content) / 1024 / 1024, 2),
                "max_mb":  settings.MAX_UPLOAD_SIZE_MB,
            },
        )

    # ── Security Scan (Tier 1) ─────────────────────────────────────────────────
    sec_report = upload_security.assert_upload_safe(
        file_bytes   = content,
        filename     = file.filename or "upload",
        max_size_mb  = settings.MAX_UPLOAD_SIZE_MB,
    )
    if not sec_report.is_safe:
        raise FileUploadException(
            message = f"File rejected by security scan: {sec_report.findings}",
            details = sec_report.as_dict(),
        )

    # ── Duplicate check ───────────────────────────────────────────────────────
    file_hash = generate_file_hash(content)
    repo      = ResumeRepository(db)

    existing = repo.get_by_file_hash(file_hash)
    if existing:
        logger.info(
            f"Duplicate file detected: hash={file_hash[:8]}... "
            f"existing_id={existing.id}"
        )
        return ResumeUploadResponse(
            resume_id         = existing.id,
            original_filename = existing.original_filename,
            file_size_kb      = existing.file_size_kb or 0,
            status            = existing.status,
            message           = "Duplicate file detected — returning existing record",
        )

    # ── Save file ─────────────────────────────────────────────────────────────
    try:
        save_result = file_handler.save(file)
    except Exception as e:
        logger.error(f"File save failed: {e}")
        raise FileUploadException(f"Failed to save file: {str(e)}")

    # ── Create DB record ──────────────────────────────────────────────────────
    ext = get_file_extension(file.filename or "resume.pdf")
    resume = repo.create({
        "original_filename": file.filename or "resume.pdf",
        "stored_filename":   save_result["stored_filename"],
        "file_path":         save_result["file_path"],
        "file_size_bytes":   save_result["file_size_bytes"],
        "file_hash":         file_hash,
        "file_extension":    ext,
        "status":            "pending",
    })

    logger.info(
        f"Resume uploaded: id={resume.id} | "
        f"file={file.filename} | "
        f"size={save_result['file_size_bytes']} bytes"
    )

    # ── Queue extraction ──────────────────────────────────────────────────────
    background_tasks.add_task(
        _extract_resume_background,
        resume_id = str(resume.id),
        file_path = save_result["file_path"],
    )

    return ResumeUploadResponse(
        resume_id         = resume.id,
        original_filename = file.filename or "resume.pdf",
        file_size_kb      = round(save_result["file_size_bytes"] / 1024, 2),
        status            = "pending",
        message           = "Resume uploaded successfully. Extraction queued.",
    )


@router.post(
    "/batch",
    response_model=list[ResumeUploadResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload multiple resumes",
    description="Upload up to 20 resume files in a single request.",
)
async def upload_resumes_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(
        ...,
        description="PDF resume files (max 20 files, 10MB each)",
    ),
    db: Session = Depends(get_db),
) -> list[ResumeUploadResponse]:
    """Upload multiple resume files at once."""

    if len(files) > 20:
        raise FileUploadException(
            message = "Too many files. Maximum 20 files per batch.",
            details = {"count": len(files), "max": 20},
        )

    responses = []
    repo      = ResumeRepository(db)

    for file in files:
        try:
            _validate_upload_file(file)
            content = await file.read()
            await file.seek(0)

            if len(content) > settings.max_upload_size_bytes:
                responses.append(ResumeUploadResponse(
                    resume_id         = generate_uuid(),
                    original_filename = file.filename or "unknown",
                    file_size_kb      = 0,
                    status            = "failed",
                    message           = f"File too large: {file.filename}",
                ))
                continue

            # Duplicate check
            file_hash = generate_file_hash(content)
            existing  = repo.get_by_file_hash(file_hash)
            if existing:
                responses.append(ResumeUploadResponse(
                    resume_id         = existing.id,
                    original_filename = existing.original_filename,
                    file_size_kb      = existing.file_size_kb or 0,
                    status            = existing.status,
                    message           = "Duplicate — returning existing record",
                ))
                continue

            # Save and create record
            save_result = file_handler.save(file)
            ext         = get_file_extension(file.filename or "")
            resume      = repo.create({
                "original_filename": file.filename or "resume.pdf",
                "stored_filename":   save_result["stored_filename"],
                "file_path":         save_result["file_path"],
                "file_size_bytes":   save_result["file_size_bytes"],
                "file_hash":         file_hash,
                "file_extension":    ext,
                "status":            "pending",
            })

            background_tasks.add_task(
                _extract_resume_background,
                resume_id = str(resume.id),
                file_path = save_result["file_path"],
            )

            responses.append(ResumeUploadResponse(
                resume_id         = resume.id,
                original_filename = file.filename or "resume.pdf",
                file_size_kb      = round(
                    save_result["file_size_bytes"] / 1024, 2
                ),
                status  = "pending",
                message = "Queued for extraction",
            ))

        except FileUploadException as e:
            responses.append(ResumeUploadResponse(
                resume_id         = generate_uuid(),
                original_filename = file.filename or "unknown",
                file_size_kb      = 0,
                status            = "failed",
                message           = e.message,
            ))
        except Exception as e:
            logger.error(f"Batch upload error for {file.filename}: {e}")
            responses.append(ResumeUploadResponse(
                resume_id         = generate_uuid(),
                original_filename = file.filename or "unknown",
                file_size_kb      = 0,
                status            = "failed",
                message           = f"Upload failed: {str(e)}",
            ))

    logger.info(
        f"Batch upload: {len(files)} files | "
        f"{sum(1 for r in responses if r.status == 'pending')} queued"
    )
    return responses


@router.get(
    "/{resume_id}/status",
    response_model=ResumeStatusResponse,
    summary="Get resume processing status",
)
async def get_resume_status(
    resume_id: str,
    db: Session = Depends(get_db),
) -> ResumeStatusResponse:
    """Get the current processing status of a resume."""
    repo   = ResumeRepository(db)
    resume = repo.get_by_id(resume_id)

    if not resume:
        raise FileNotFoundException("Resume", resume_id)

    return ResumeStatusResponse(
        resume_id           = resume.id,
        status              = resume.status,
        pdf_type            = resume.pdf_type,
        page_count          = resume.page_count,
        overall_confidence  = resume.overall_confidence,
        processing_duration = resume.processing_duration,
        error_message       = resume.error_message,
        uploaded_at         = resume.uploaded_at,
        processed_at        = resume.processed_at,
    )


@router.get(
    "/",
    response_model=ResumeListResponse,
    summary="List all resumes",
)
async def list_resumes(
    page:      int = 1,
    page_size: int = 20,
    status:    str = None,
    db: Session = Depends(get_db),
) -> ResumeListResponse:
    """List all uploaded resumes with pagination."""
    repo   = ResumeRepository(db)
    skip   = (page - 1) * page_size

    if status:
        resumes = repo.get_by_status(status, skip=skip, limit=page_size)
        total   = repo.count({"status": status})
    else:
        resumes = repo.get_all(skip=skip, limit=page_size, order_by="uploaded_at")
        total   = repo.count()

    items = [
        ResumeSummary(
            resume_id          = r.id,
            original_filename  = r.original_filename,
            status             = r.status,
            overall_confidence = r.overall_confidence,
            candidate_name     = (
                r.extracted_data.get("contact", {}).get("full_name")
                if r.extracted_data else None
            ),
            candidate_email    = (
                r.extracted_data.get("contact", {}).get("email")
                if r.extracted_data else None
            ),
            uploaded_at        = r.uploaded_at,
        )
        for r in resumes
    ]

    return ResumeListResponse(
        items     = items,
        total     = total,
        page      = page,
        page_size = page_size,
        has_next  = (skip + page_size) < total,
    )


@router.delete(
    "/{resume_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a resume",
)
async def delete_resume(
    resume_id: str,
    db: Session = Depends(get_db),
) -> None:
    """Delete a resume record and its associated file."""
    repo   = ResumeRepository(db)
    resume = repo.get_by_id(resume_id)

    if not resume:
        raise FileNotFoundException("Resume", resume_id)

    # Delete file from storage
    try:
        file_handler.delete(resume.file_path)
    except Exception as e:
        logger.warning(f"Could not delete file {resume.file_path}: {e}")

    # Delete DB record
    repo.delete(resume_id)
    logger.info(f"Resume deleted: id={resume_id}")


@router.get(
    "/stats",
    response_model=ProcessingStats,
    summary="Get processing statistics",
)
async def get_stats(
    db: Session = Depends(get_db),
) -> ProcessingStats:
    """Get overall processing statistics."""
    repo  = ResumeRepository(db)
    stats = repo.get_statistics()

    return ProcessingStats(
        total_uploaded  = repo.count(),
        total_completed = repo.count({"status": "completed"}),
        total_failed    = repo.count({"status": "failed"}),
        total_pending   = repo.count({"status": "pending"}),
        avg_confidence  = stats.get("completed", {}).get("avg_confidence", 0.0),
        avg_duration_s  = stats.get("completed", {}).get("avg_duration", 0.0),
    )


# ─── Background Task ───────────────────────────────────────────────────────────
async def _extract_resume_background(
    resume_id: str,
    file_path: str,
) -> None:
    """
    Background task: run extraction pipeline on uploaded resume.
    Updates DB record with results.
    """
    from app.database.connection import get_db_context
    from app.core.pipeline import extraction_pipeline

    logger.info(f"Background extraction started: resume_id={resume_id}")

    with get_db_context() as db:
        repo = ResumeRepository(db)

        # Mark as processing
        repo.mark_as_processing(resume_id)

        try:
            start = time.time()

            # Run pipeline
            result = extraction_pipeline.run(
                file_path = file_path,
                resume_id = resume_id,
            )

            schema      = result["schema"]
            pdf_meta    = result["pdf_metadata"]
            duration    = round(time.time() - start, 2)
            confidence  = result["overall_confidence"]

            # Serialize schema to dict
            extracted_data = schema.model_dump()

            # Mark as completed
            repo.mark_as_completed(
                resume_id      = resume_id,
                extracted_data = extracted_data,
                duration       = duration,
                confidence     = confidence,
            )

            # Update PDF metadata
            repo.update(resume_id, {
                "pdf_type":      pdf_meta.get("pdf_type"),
                "page_count":    pdf_meta.get("page_count"),
                "has_images":    pdf_meta.get("has_images"),
                "has_tables":    pdf_meta.get("has_tables"),
                "is_multicolumn":pdf_meta.get("is_multicolumn"),
                "raw_text_length": len(schema.summary or ""),
                "field_confidences": {
                    k: v for k, v in result.get("timings", {}).items()
                },
            })

            # Create/update candidate record
            from app.database.resume_repository import CandidateRepository
            candidate_repo = CandidateRepository(db)
            candidate      = candidate_repo.upsert_from_extraction(
                extracted_data, resume_id
            )

            # Link candidate to resume
            repo.update(resume_id, {"candidate_id": str(candidate.id)})

            logger.info(
                f"Background extraction complete: "
                f"resume_id={resume_id} | "
                f"duration={duration}s | "
                f"confidence={confidence:.3f}"
            )

        except Exception as e:
            logger.error(
                f"Background extraction failed: "
                f"resume_id={resume_id} | error={str(e)}"
            )
            repo.mark_as_failed(resume_id, str(e))
