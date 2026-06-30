# app/utils/logger.py

import sys
from pathlib import Path
from loguru import logger


def setup_logger(
    log_level: str = "INFO",
    log_dir: Path = Path("logs"),
    rotation: str = "10 MB",
    retention: str = "30 days",
) -> None:
    """
    Configure Loguru logger with:
    - Colored console output
    - Rotating file output (general + errors only)
    """

    # ─── Remove default handler ────────────────────────────────────────────────
    logger.remove()

    # ─── Console Handler ───────────────────────────────────────────────────────
    log_format_console = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    logger.add(
        sys.stdout,
        format=log_format_console,
        level=log_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # ─── General File Handler ──────────────────────────────────────────────────
    log_format_file = (
        "{time:YYYY-MM-DD HH:mm:ss} | "
        "{level: <8} | "
        "{name}:{function}:{line} | "
        "{message}"
    )

    try:
        logger.add(
            log_dir / "app.log",
            format=log_format_file,
            level=log_level,
            rotation=rotation,
            retention=retention,
            compression="zip",
            backtrace=True,
            diagnose=False,
            enqueue=True,          # Thread-safe async logging
        )
    except PermissionError as e:
        print(f"CRITICAL: Failed to initialize file logger at {log_dir / 'app.log'}: {e}")
        print("Falling back to console-only logging.")

    # ─── Error-Only File Handler ───────────────────────────────────────────────
    try:
        logger.add(
            log_dir / "errors.log",
            format=log_format_file,
            level="ERROR",
            rotation=rotation,
            retention=retention,
            compression="zip",
            backtrace=True,
            diagnose=True,
            enqueue=True,
        )
    except PermissionError:
        pass  # Already warned above

    logger.info(f"Logger initialized | level={log_level} | log_dir={log_dir}")


def get_logger(name: str):
    """Return a named logger context for module-level use."""
    return logger.bind(name=name)


# ─── Initialize on import ──────────────────────────────────────────────────────
from app.config import settings

setup_logger(
    log_level=settings.LOG_LEVEL,
    log_dir=settings.LOG_DIR,
    rotation=settings.LOG_ROTATION,
    retention=settings.LOG_RETENTION,
)
