# app/storage/temp_manager.py

import os
import shutil
import time
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from app.config import settings
from app.utils.logger import get_logger
from app.utils.helpers import generate_uuid

logger = get_logger(__name__)


class TempManager:
    """
    Manages temporary files created during resume processing.
    Ensures cleanup of temp files after processing completes
    or fails, preventing disk space leaks.
    """

    def __init__(self, temp_dir: Path = settings.TEMP_DIR):
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    # ─── Create Temp File ──────────────────────────────────────────────────────
    def create_temp_path(
        self,
        suffix: str = ".pdf",
        prefix: str = "resume_",
    ) -> Path:
        """
        Generate a unique temp file path (does not create the file).
        """
        uid = generate_uuid().replace("-", "")[:10]
        filename = f"{prefix}{uid}{suffix}"
        return self.temp_dir / filename

    def write_temp_file(
        self,
        content: bytes,
        suffix: str = ".pdf",
        prefix: str = "resume_",
    ) -> Path:
        """
        Write bytes to a new temp file and return its path.
        """
        temp_path = self.create_temp_path(suffix=suffix, prefix=prefix)
        try:
            with open(temp_path, "wb") as f:
                f.write(content)
            logger.debug(f"Temp file created: {temp_path}")
            return temp_path
        except Exception as e:
            logger.error(f"Failed to write temp file: {e}")
            raise

    # ─── Cleanup ───────────────────────────────────────────────────────────────
    def delete_file(self, path: Path | str) -> bool:
        """Delete a specific temp file."""
        try:
            path = Path(path)
            if path.exists():
                path.unlink()
                logger.debug(f"Temp file deleted: {path}")
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to delete temp file {path}: {e}")
            return False

    def delete_files(self, paths: list[Path | str]) -> int:
        """Delete multiple temp files. Returns count of deleted files."""
        deleted = 0
        for path in paths:
            if self.delete_file(path):
                deleted += 1
        return deleted

    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        """
        Delete temp files older than max_age_hours.
        Useful for scheduled cleanup tasks.
        Returns count of deleted files.
        """
        deleted = 0
        cutoff = time.time() - (max_age_hours * 3600)

        for file_path in self.temp_dir.iterdir():
            if file_path.is_file():
                try:
                    if file_path.stat().st_mtime < cutoff:
                        file_path.unlink()
                        deleted += 1
                        logger.debug(f"Cleaned up old temp file: {file_path}")
                except Exception as e:
                    logger.warning(f"Could not delete temp file {file_path}: {e}")

        if deleted:
            logger.info(f"Temp cleanup: deleted {deleted} files older than {max_age_hours}h")
        return deleted

    def cleanup_all(self) -> int:
        """Delete all files in the temp directory."""
        deleted = 0
        for file_path in self.temp_dir.iterdir():
            if file_path.is_file():
                try:
                    file_path.unlink()
                    deleted += 1
                except Exception as e:
                    logger.warning(f"Could not delete {file_path}: {e}")
        logger.info(f"Cleaned up all {deleted} temp files")
        return deleted

    def get_temp_dir_size_mb(self) -> float:
        """Return total size of temp directory in MB."""
        total = sum(
            f.stat().st_size
            for f in self.temp_dir.iterdir()
            if f.is_file()
        )
        return round(total / (1024 * 1024), 2)

    # ─── Context Manager ───────────────────────────────────────────────────────
    @contextmanager
    def temp_file(
        self,
        content: Optional[bytes] = None,
        suffix: str = ".pdf",
        prefix: str = "resume_",
    ):
        """
        Context manager that creates a temp file and guarantees
        cleanup on exit — even if an exception occurs.

        Usage:
            with temp_manager.temp_file(pdf_bytes, suffix=".pdf") as path:
                result = process(path)
            # File is automatically deleted here
        """
        temp_path = None
        try:
            if content is not None:
                temp_path = self.write_temp_file(content, suffix, prefix)
            else:
                temp_path = self.create_temp_path(suffix, prefix)
            yield temp_path
        finally:
            if temp_path:
                self.delete_file(temp_path)

    @contextmanager
    def temp_directory(self, prefix: str = "resume_dir_"):
        """
        Context manager for a temporary subdirectory.
        Entire directory is deleted on exit.
        """
        uid = generate_uuid().replace("-", "")[:8]
        dir_path = self.temp_dir / f"{prefix}{uid}"
        dir_path.mkdir(parents=True, exist_ok=True)
        try:
            yield dir_path
        finally:
            try:
                shutil.rmtree(dir_path, ignore_errors=True)
                logger.debug(f"Temp directory deleted: {dir_path}")
            except Exception as e:
                logger.warning(f"Could not delete temp directory {dir_path}: {e}")


# ─── Singleton ─────────────────────────────────────────────────────────────────
temp_manager = TempManager()
