# app/api/routes/export.py

from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.utils.logger import get_logger
from app.utils.helpers import build_export_filename
from app.database.connection import get_db
from app.database.resume_repository import ResumeRepository, CandidateRepository
from app.models.schemas.resume_schema import ExportRequest, ExportResponse
from app.models.schemas.extracted_data import ExtractedResumeSchema
from app.export.excel_exporter import excel_exporter
from app.export.csv_exporter   import csv_exporter
from app.api.middleware.error_handler import (
    FileNotFoundException,
    ExportException,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/export", tags=["Export"])


# ─── Helpers ───────────────────────────────────────────────────────────────────
def _load_schemas(
    resume_ids: Optional[list] = None,
    db: Session = None,
) -> list[tuple[ExtractedResumeSchema, dict]]:
    """
    Load and deserialize extracted schemas from DB.
    Returns list of (schema, metadata) tuples.
    """
    repo = ResumeRepository(db)

    if resume_ids:
        resumes = [
            repo.get_by_id(str(rid))
            for rid in resume_ids
        ]
        resumes = [r for r in resumes if r]
    else:
        resumes = repo.get_by_status("completed", limit=1000)

    schemas = []
    for resume in resumes:
        if not resume.extracted_data:
            continue
        try:
            schema   = ExtractedResumeSchema(**resume.extracted_data)
            metadata = {
                "resume_id":    str(resume.id),
                "filename":     resume.original_filename,
                "uploaded_at":  resume.uploaded_at.strftime("%Y-%m-%d")
                                if resume.uploaded_at else "",
                "processed_at": resume.processed_at.strftime("%Y-%m-%d")
                                if resume.processed_at else "",
                "confidence":   resume.overall_confidence or 0,
            }
            schemas.append((schema, metadata))
        except Exception as e:
            logger.warning(
                f"Failed to deserialize schema for "
                f"resume {resume.id}: {e}"
            )

    return schemas


# ─── Routes ────────────────────────────────────────────────────────────────────
@router.post(
    "/",
    response_model=ExportResponse,
    summary="Generate export file",
    description=(
        "Generate an Excel or CSV export of extracted resume data. "
        "Returns a download URL."
    ),
)
async def generate_export(
    request: ExportRequest,
    db: Session = Depends(get_db),
) -> ExportResponse:
    """
    Generate an export file (Excel or CSV).

    Supports:
      - Specific resume IDs or all completed resumes
      - Excel (.xlsx) or CSV format
      - Date range filtering
    """
    logger.info(
        f"Export requested: format={request.format}, "
        f"ids={len(request.resume_ids) if request.resume_ids else 'all'}"
    )

    # Load schemas
    schemas = _load_schemas(request.resume_ids, db)

    if not schemas:
        raise ExportException(
            "No completed resumes found to export"
        )

    # Apply date filter
    if request.date_from or request.date_to:
        schemas = _filter_by_date(schemas, request.date_from, request.date_to)

    if not schemas:
        raise ExportException(
            "No resumes match the specified date range"
        )

    # Generate export
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if request.format == "excel":
            filename    = f"resumes_export_{timestamp}.xlsx"
            output_path = excel_exporter.export(schemas)
            media_type  = (
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            )

        else:  # csv
            filename    = f"resumes_export_{timestamp}.csv"
            output_path = csv_exporter.export(schemas)
            media_type  = "text/csv"

        download_url = f"/api/v1/export/download/{output_path.name}"

        logger.info(
            f"Export generated: {output_path.name} | "
            f"{len(schemas)} records"
        )

        return ExportResponse(
            export_id    = output_path.stem,
            filename     = output_path.name,
            download_url = download_url,
            record_count = len(schemas),
            format       = request.format,
            created_at   = datetime.now(),
        )

    except Exception as e:
        logger.error(f"Export generation failed: {e}")
        raise ExportException(f"Export failed: {str(e)}")


@router.get(
    "/download/{filename}",
    summary="Download export file",
    description="Download a previously generated export file.",
)
async def download_export(filename: str) -> FileResponse:
    """Download a generated export file by filename."""
    from app.config import settings

    # Security: prevent path traversal
    safe_name = Path(filename).name
    file_path = settings.EXPORT_DIR / safe_name

    if not file_path.exists():
        raise FileNotFoundException("Export file", filename)

    # Determine media type
    suffix = file_path.suffix.lower()
    if suffix == ".xlsx":
        media_type = (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        )
    elif suffix == ".csv":
        media_type = "text/csv"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path         = str(file_path),
        filename     = safe_name,
        media_type   = media_type,
    )


@router.get(
    "/stream/csv",
    summary="Stream CSV export",
    description=(
        "Stream CSV data directly without saving to disk. "
        "Ideal for real-time downloads."
    ),
)
async def stream_csv_export(
    resume_ids: Optional[str] = Query(
        default=None,
        description="Comma-separated resume IDs (optional)",
    ),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream CSV export directly to client."""

    # Parse resume IDs
    ids = None
    if resume_ids:
        ids = [rid.strip() for rid in resume_ids.split(",") if rid.strip()]

    schemas = _load_schemas(ids, db)

    if not schemas:
        raise ExportException("No completed resumes found")

    # Generate CSV bytes
    try:
        csv_bytes = csv_exporter.export_to_bytes(schemas)
    except Exception as e:
        raise ExportException(f"CSV generation failed: {str(e)}")

    filename = build_export_filename("resumes_export", "csv")

    return StreamingResponse(
        content     = iter([csv_bytes]),
        media_type  = "text/csv",
        headers     = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":       str(len(csv_bytes)),
        },
    )


@router.get(
    "/{resume_id}/excel",
    summary="Export single resume to Excel",
)
async def export_single_excel(
    resume_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Export a single resume to Excel."""
    repo   = ResumeRepository(db)
    resume = repo.get_by_id(resume_id)

    if not resume:
        raise FileNotFoundException("Resume", resume_id)

    if not resume.extracted_data:
        raise ExportException(
            f"Resume {resume_id} has not been extracted yet"
        )

    try:
        schema   = ExtractedResumeSchema(**resume.extracted_data)
        metadata = {
            "resume_id":  str(resume.id),
            "filename":   resume.original_filename,
            "confidence": resume.overall_confidence or 0,
        }

        output_path = excel_exporter.export_single(schema, metadata)

        return FileResponse(
            path       = str(output_path),
            filename   = output_path.name,
            media_type = (
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
        )

    except Exception as e:
        raise ExportException(f"Single export failed: {str(e)}")


@router.get(
    "/{resume_id}/csv",
    summary="Export single resume to CSV",
)
async def export_single_csv(
    resume_id: str,
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Export a single resume to CSV as streaming response."""
    repo   = ResumeRepository(db)
    resume = repo.get_by_id(resume_id)

    if not resume:
        raise FileNotFoundException("Resume", resume_id)

    if not resume.extracted_data:
        raise ExportException(
            f"Resume {resume_id} has not been extracted yet"
        )

    try:
        schema    = ExtractedResumeSchema(**resume.extracted_data)
        metadata  = {"resume_id": str(resume.id)}
        csv_str   = csv_exporter.single_to_string(schema, metadata)
        csv_bytes = csv_str.encode("utf-8-sig")
        filename  = build_export_filename(
            resume.original_filename.replace(".pdf", ""), "csv"
        )

        return StreamingResponse(
            content    = iter([csv_bytes]),
            media_type = "text/csv",
            headers    = {
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    except Exception as e:
        raise ExportException(f"CSV export failed: {str(e)}")


# ─── Helpers ───────────────────────────────────────────────────────────────────
def _filter_by_date(
    schemas:   list[tuple],
    date_from: Optional[datetime],
    date_to:   Optional[datetime],
) -> list[tuple]:
    """Filter schemas by upload/process date."""
    filtered = []
    for schema, metadata in schemas:
        uploaded_str = metadata.get("uploaded_at", "")
        try:
            uploaded = datetime.strptime(uploaded_str, "%Y-%m-%d")
            if date_from and uploaded < date_from:
                continue
            if date_to and uploaded > date_to:
                continue
            filtered.append((schema, metadata))
        except (ValueError, TypeError):
            filtered.append((schema, metadata))
    return filtered
