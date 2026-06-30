# app/api/middleware/error_handler.py

import traceback
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from pydantic import ValidationError

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ─── Custom Exceptions ─────────────────────────────────────────────────────────
class ResumeExtractorException(Exception):
    """Base exception for all Resume Extractor errors."""
    def __init__(
        self,
        message:     str,
        status_code: int = 500,
        details:     dict = None,
    ):
        self.message     = message
        self.status_code = status_code
        self.details     = details or {}
        super().__init__(message)


class FileUploadException(ResumeExtractorException):
    """Raised when file upload fails validation."""
    def __init__(self, message: str, details: dict = None):
        super().__init__(message, status_code=400, details=details or {})


class FileNotFoundException(ResumeExtractorException):
    """Raised when a requested file or resource is not found."""
    def __init__(self, resource: str, resource_id: str):
        super().__init__(
            message     = f"{resource} not found: {resource_id}",
            status_code = 404,
            details     = {"resource": resource, "id": resource_id},
        )


class ExtractionException(ResumeExtractorException):
    """Raised when extraction pipeline fails."""
    def __init__(self, message: str, resume_id: str = None):
        super().__init__(
            message     = message,
            status_code = 422,
            details     = {"resume_id": resume_id},
        )


class ExportException(ResumeExtractorException):
    """Raised when export generation fails."""
    def __init__(self, message: str):
        super().__init__(message, status_code=500)


class DatabaseException(ResumeExtractorException):
    """Raised when a database operation fails."""
    def __init__(self, message: str):
        super().__init__(message, status_code=503)


# ─── Error Response Builder ────────────────────────────────────────────────────
def build_error_response(
    status_code: int,
    message:     str,
    error_type:  str,
    details:     dict = None,
    request_id:  str  = None,
) -> dict:
    """Build a standardized error response body."""
    return {
        "success":    False,
        "error": {
            "type":       error_type,
            "message":    message,
            "details":    details or {},
            "request_id": request_id,
        },
    }


# ─── Exception Handlers ────────────────────────────────────────────────────────
async def resume_extractor_exception_handler(
    request: Request,
    exc:     ResumeExtractorException,
) -> JSONResponse:
    """Handle all custom ResumeExtractor exceptions."""
    request_id = getattr(request.state, "request_id", None)

    logger.warning(
        f"ResumeExtractorException: {exc.message} | "
        f"status={exc.status_code} | "
        f"request_id={request_id}"
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_response(
            status_code = exc.status_code,
            message     = exc.message,
            error_type  = type(exc).__name__,
            details     = exc.details,
            request_id  = request_id,
        ),
    )


async def validation_exception_handler(
    request: Request,
    exc:     RequestValidationError,
) -> JSONResponse:
    """Handle Pydantic/FastAPI request validation errors."""
    request_id = getattr(request.state, "request_id", None)

    # Format validation errors
    errors = []
    for error in exc.errors():
        errors.append({
            "field":   " → ".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type":    error["type"],
        })

    logger.warning(
        f"Validation error: {len(errors)} field(s) | "
        f"path={request.url.path} | "
        f"request_id={request_id}"
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=build_error_response(
            status_code = 422,
            message     = "Request validation failed",
            error_type  = "ValidationError",
            details     = {"errors": errors},
            request_id  = request_id,
        ),
    )


async def sqlalchemy_exception_handler(
    request: Request,
    exc:     SQLAlchemyError,
) -> JSONResponse:
    """Handle SQLAlchemy database errors."""
    request_id = getattr(request.state, "request_id", None)

    logger.error(
        f"Database error: {str(exc)} | "
        f"path={request.url.path} | "
        f"request_id={request_id}"
    )

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=build_error_response(
            status_code = 503,
            message     = "Database service unavailable",
            error_type  = "DatabaseError",
            request_id  = request_id,
        ),
    )


async def unhandled_exception_handler(
    request: Request,
    exc:     Exception,
) -> JSONResponse:
    """Catch-all handler for unhandled exceptions."""
    request_id = getattr(request.state, "request_id", None)

    # Log full traceback for debugging
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)} | "
        f"path={request.url.path} | "
        f"request_id={request_id}\n"
        f"{traceback.format_exc()}"
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=build_error_response(
            status_code = 500,
            message     = "An unexpected error occurred",
            error_type  = "InternalServerError",
            request_id  = request_id,
        ),
    )
