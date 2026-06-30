# app/database/connection.py

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase
from sqlalchemy.pool import QueuePool

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ─── Declarative Base ──────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.
    All models must inherit from this class.
    """
    pass


# ─── Engine ────────────────────────────────────────────────────────────────────
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,          # Verify connection before using from pool
    pool_recycle=1800,           # Recycle connections every 30 minutes
    echo=settings.DB_ECHO,       # Log SQL queries if enabled
    connect_args=(
        {"options": "-c timezone=utc"}
        if "postgresql" in settings.DATABASE_URL
        else {}
    ),
)


# ─── Session Factory ───────────────────────────────────────────────────────────
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,     # Keep objects accessible after commit
)


# ─── Engine Events ─────────────────────────────────────────────────────────────
@event.listens_for(engine, "connect")
def on_connect(dbapi_connection, connection_record):
    logger.debug("New database connection established")


@event.listens_for(engine, "checkout")
def on_checkout(dbapi_connection, connection_record, connection_proxy):
    logger.debug("Database connection checked out from pool")


# ─── Dependency: FastAPI DB Session ───────────────────────────────────────────
def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session per request.
    Automatically commits on success and rolls back on exception.

    Usage:
        @router.post("/example")
        def example(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Database session error, rolling back: {e}")
        raise
    finally:
        db.close()


# ─── Context Manager: Manual DB Session ───────────────────────────────────────
@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager for database sessions outside of FastAPI
    dependency injection (e.g., background tasks, scripts).

    Usage:
        with get_db_context() as db:
            db.add(some_model)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Database context error, rolling back: {e}")
        raise
    finally:
        db.close()


# ─── Table Management ──────────────────────────────────────────────────────────
def create_all_tables() -> None:
    """Create all tables defined in ORM models (used in dev/testing)."""
    logger.info("Creating all database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("All tables created successfully")


def drop_all_tables() -> None:
    """Drop all tables — use with caution (testing only)."""
    logger.warning("Dropping all database tables...")
    Base.metadata.drop_all(bind=engine)
    logger.warning("All tables dropped")


# ─── Health Check ──────────────────────────────────────────────────────────────
def check_db_connection() -> bool:
    """
    Verify database connectivity.
    Returns True if connection is healthy, False otherwise.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("Database connection check: OK")
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False
