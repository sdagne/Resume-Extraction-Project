from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.utils.logger import get_logger
from app.database.connection import (
    create_all_tables,
    check_db_connection,
)
from app.api.routes import (
    upload_router,
    extract_router,
    export_router,
)
from app.api.middleware.error_handler import (
    ResumeExtractorException,
    resume_extractor_exception_handler,
    validation_exception_handler,
    sqlalchemy_exception_handler,
    unhandled_exception_handler,
)
from app.api.middleware.request_logger import RequestLoggerMiddleware

logger = get_logger(__name__)


# ─── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan handler.
    Runs startup and shutdown logic.
    """
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"  Environment : {settings.APP_ENV}")
    logger.info(f"  Debug mode  : {settings.DEBUG}")
    logger.info("=" * 60)

    # Ensure directories exist
    settings.ensure_directories()
    logger.info("Storage directories verified")

    # Database connectivity check
    if check_db_connection():
        logger.info("Database connection: OK")
    else:
        logger.error("Database connection: FAILED")

    # Create tables in development mode
    if settings.is_development:
        try:
            create_all_tables()
            logger.info("Database tables verified/created")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")

    # Pre-warm NLP models (optional — reduces first-request latency)
    if not settings.is_development:
        try:
            logger.info("Pre-warming NLP models...")
            from app.nlp.ner_engine import ner_engine
            _ = ner_engine.nlp   # Trigger lazy load
            logger.info("NLP models loaded")
        except Exception as e:
            logger.warning(f"NLP pre-warm failed: {e}")

    logger.info(f"Application started on {settings.HOST}:{settings.PORT}")
    logger.info(f"API docs: http://{settings.HOST}:{settings.PORT}/docs")

    yield   # Application runs here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Application shutting down...")

    # Cleanup temp files
    try:
        from app.storage.temp_manager import temp_manager
        deleted = temp_manager.cleanup_old_files(max_age_hours=0)
        logger.info(f"Cleaned up {deleted} temp files on shutdown")
    except Exception as e:
        logger.warning(f"Temp cleanup on shutdown failed: {e}")

    logger.info("Application shutdown complete")


# ─── App Factory ───────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    Uses the factory pattern for testability.
    """
    app = FastAPI(
        title       = settings.APP_NAME,
        version     = settings.APP_VERSION,
        description = """
## Resume Extractor API

A high-accuracy resume extraction system that converts PDF resumes
into structured JSON data without using any LLM.

### Features
- 📄 **PDF Parsing**: Digital PDFs (PyMuPDF) + Scanned PDFs (PaddleOCR)
- 🧠 **Layout Analysis**: Multi-column, sidebar, and mixed layouts
- 🔍 **Field Extraction**: Contact, Experience, Education, Skills, Certifications
- ✅ **Validation**: Field-level validation and confidence scoring
- 📊 **Export**: Excel (.xlsx) and CSV with professional formatting

### Pipeline
Upload → PDF Detection → Text Extraction → Layout Analysis
→ Field Extraction → Skill Matching → Validation
→ Confidence Scoring → Export

        """,
        docs_url    = "/docs"    if not settings.is_production else None,
        redoc_url   = "/redoc"   if not settings.is_production else None,
        openapi_url = "/openapi.json" if not settings.is_production else None,
        lifespan    = lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = settings.CORS_ORIGINS,
        allow_credentials = True,
        allow_methods     = ["*"],
        allow_headers     = ["*"],
        expose_headers    = ["X-Request-ID", "X-Process-Time"],
    )

    # GZip compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # Request logging
    app.add_middleware(RequestLoggerMiddleware)

    # ── Exception Handlers ────────────────────────────────────────────────────
    app.add_exception_handler(
        ResumeExtractorException,
        resume_extractor_exception_handler,
    )
    app.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )
    app.add_exception_handler(
        SQLAlchemyError,
        sqlalchemy_exception_handler,
    )
    app.add_exception_handler(
        Exception,
        unhandled_exception_handler,
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    prefix = settings.API_PREFIX

    app.include_router(upload_router,  prefix=prefix)
    app.include_router(extract_router, prefix=prefix)
    app.include_router(export_router,  prefix=prefix)

    # ── Health & Root Endpoints ───────────────────────────────────────────────
    @app.get("/", tags=["Root"], summary="API root")
    async def root():
        return {
            "name":    settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status":  "running",
            "docs":    "/docs",
        }

    @app.get("/health", tags=["Health"], summary="Health check")
    async def health_check():
        """
        Health check endpoint.
        Returns database and storage status.
        """
        db_ok      = check_db_connection()
        storage_ok = settings.UPLOAD_DIR.exists()

        status_code = 200 if db_ok and storage_ok else 503

        return {
            "status":   "healthy" if db_ok and storage_ok else "degraded",
            "version":  settings.APP_VERSION,
            "checks": {
                "database": "ok" if db_ok      else "error",
                "storage":  "ok" if storage_ok else "error",
            },
        }

    @app.get("/health/detailed", tags=["Health"], summary="Detailed health")
    async def detailed_health():
        """Detailed health check with component status."""
        from app.storage.temp_manager import temp_manager

        db_ok        = check_db_connection()
        storage_ok   = settings.UPLOAD_DIR.exists()
        temp_size_mb = temp_manager.get_temp_dir_size_mb()

        return {
            "status":  "healthy" if db_ok and storage_ok else "degraded",
            "version": settings.APP_VERSION,
            "environment": settings.APP_ENV,
            "components": {
                "database": {
                    "status": "ok" if db_ok else "error",
                    "url":    settings.DATABASE_URL.split("@")[-1]
                              if "@" in settings.DATABASE_URL else "local",
                },
                "storage": {
                    "status":    "ok" if storage_ok else "error",
                    "upload_dir":str(settings.UPLOAD_DIR),
                    "export_dir":str(settings.EXPORT_DIR),
                },
                "temp": {
                    "size_mb": temp_size_mb,
                    "dir":     str(settings.TEMP_DIR),
                },
            },
        }

    return app


# ─── App Instance ──────────────────────────────────────────────────────────────
app = create_app()


# ─── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host        = settings.HOST,
        port        = settings.PORT,
        reload      = settings.is_development,
        log_level   = settings.LOG_LEVEL.lower(),
        workers     = 1 if settings.is_development else 4,
    )
