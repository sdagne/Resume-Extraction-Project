# app/storage/file_handler.py

import os
import shutil
from pathlib import Path
from typing import Optional, BinaryIO
from datetime import datetime

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from fastapi import UploadFile

from app.config import settings
from app.utils.logger import get_logger
from app.utils.helpers import (
    generate_uuid,
    generate_file_hash,
    get_file_extension,
    sanitize_filename,
)

logger = get_logger(__name__)


class LocalFileHandler:
    """
    Handles file storage on the local filesystem.
    Organizes files into date-based subdirectories.
    """

    def __init__(self, base_dir: Path = settings.UPLOAD_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ─── Save ──────────────────────────────────────────────────────────────────
    def save(
        self,
        file: UploadFile,
        custom_filename: Optional[str] = None,
    ) -> dict:
        """
        Save an uploaded file to local storage.

        Returns:
            dict with keys: stored_filename, file_path,
                            file_size_bytes, file_hash
        """
        try:
            # Read file content
            content = file.file.read()
            file_hash = generate_file_hash(content)

            # Build filename
            ext = get_file_extension(file.filename or "resume.pdf")
            if custom_filename:
                stored_name = f"{sanitize_filename(custom_filename)}{ext}"
            else:
                uid = generate_uuid().replace("-", "")[:12]
                base = sanitize_filename(Path(file.filename).stem)
                stored_name = f"{base}_{uid}{ext}"

            # Date-based subdirectory: uploads/2024/06/
            date_subdir = self.base_dir / datetime.now().strftime("%Y/%m")
            date_subdir.mkdir(parents=True, exist_ok=True)

            file_path = date_subdir / stored_name

            # Write to disk
            with open(file_path, "wb") as f:
                f.write(content)

            logger.info(
                f"File saved locally: {file_path} "
                f"({len(content)} bytes)"
            )

            return {
                "stored_filename": stored_name,
                "file_path":       str(file_path),
                "file_size_bytes": len(content),
                "file_hash":       file_hash,
            }

        except Exception as e:
            logger.error(f"Failed to save file locally: {e}")
            raise

    def save_bytes(
        self,
        content: bytes,
        filename: str,
        subdir: Optional[str] = None,
    ) -> dict:
        """Save raw bytes to local storage."""
        try:
            file_hash = generate_file_hash(content)
            ext = get_file_extension(filename)
            uid = generate_uuid().replace("-", "")[:8]
            stored_name = f"{sanitize_filename(Path(filename).stem)}_{uid}{ext}"

            target_dir = self.base_dir / subdir if subdir else self.base_dir
            target_dir.mkdir(parents=True, exist_ok=True)

            file_path = target_dir / stored_name
            with open(file_path, "wb") as f:
                f.write(content)

            return {
                "stored_filename": stored_name,
                "file_path":       str(file_path),
                "file_size_bytes": len(content),
                "file_hash":       file_hash,
            }
        except Exception as e:
            logger.error(f"Failed to save bytes: {e}")
            raise

    # ─── Read ──────────────────────────────────────────────────────────────────
    def read(self, file_path: str) -> bytes:
        """Read file content from local storage."""
        try:
            with open(file_path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"File not found: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}")
            raise

    def get_path(self, file_path: str) -> Path:
        """Return a Path object for the given file path."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return path

    # ─── Delete ────────────────────────────────────────────────────────────────
    def delete(self, file_path: str) -> bool:
        """Delete a file from local storage."""
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                logger.info(f"Deleted file: {file_path}")
                return True
            logger.warning(f"File not found for deletion: {file_path}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            raise

    # ─── Exists ────────────────────────────────────────────────────────────────
    def exists(self, file_path: str) -> bool:
        """Check if a file exists in local storage."""
        return Path(file_path).exists()

    # ─── Copy ──────────────────────────────────────────────────────────────────
    def copy_to_temp(self, file_path: str) -> Path:
        """Copy a file to the temp directory for processing."""
        source = Path(file_path)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {file_path}")

        temp_path = settings.TEMP_DIR / f"proc_{generate_uuid()[:8]}_{source.name}"
        shutil.copy2(source, temp_path)
        logger.debug(f"Copied to temp: {temp_path}")
        return temp_path


class S3FileHandler:
    """
    Handles file storage on AWS S3.
    Used when settings.USE_S3 is True.
    """

    def __init__(self):
        self.bucket = settings.S3_BUCKET_NAME
        self.client = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )

    def save(self, file: UploadFile, custom_filename: Optional[str] = None) -> dict:
        """Upload a file to S3."""
        try:
            content = file.file.read()
            file_hash = generate_file_hash(content)

            ext = get_file_extension(file.filename or "resume.pdf")
            uid = generate_uuid().replace("-", "")[:12]
            base = sanitize_filename(Path(file.filename or "resume").stem)
            stored_name = custom_filename or f"{base}_{uid}{ext}"

            # S3 key with date prefix
            date_prefix = datetime.now().strftime("%Y/%m")
            s3_key = f"resumes/{date_prefix}/{stored_name}"

            self.client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=content,
                ContentType=self._get_content_type(ext),
            )

            logger.info(f"File uploaded to S3: s3://{self.bucket}/{s3_key}")

            return {
                "stored_filename": stored_name,
                "file_path":       s3_key,
                "file_size_bytes": len(content),
                "file_hash":       file_hash,
            }

        except (ClientError, NoCredentialsError) as e:
            logger.error(f"S3 upload failed: {e}")
            raise

    def read(self, s3_key: str) -> bytes:
        """Download file content from S3."""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=s3_key)
            return response["Body"].read()
        except ClientError as e:
            logger.error(f"S3 read failed for key {s3_key}: {e}")
            raise

    def download_to_temp(self, s3_key: str) -> Path:
        """Download S3 file to local temp directory for processing."""
        content = self.read(s3_key)
        filename = Path(s3_key).name
        temp_path = settings.TEMP_DIR / f"s3_{generate_uuid()[:8]}_{filename}"
        with open(temp_path, "wb") as f:
            f.write(content)
        logger.debug(f"Downloaded from S3 to temp: {temp_path}")
        return temp_path

    def delete(self, s3_key: str) -> bool:
        """Delete a file from S3."""
        try:
            self.client.delete_object(Bucket=self.bucket, Key=s3_key)
            logger.info(f"Deleted from S3: {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"S3 delete failed: {e}")
            return False

    def get_presigned_url(self, s3_key: str, expiry: int = 3600) -> str:
        """Generate a pre-signed download URL for a file."""
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": s3_key},
                ExpiresIn=expiry,
            )
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise

    def _get_content_type(self, ext: str) -> str:
        mapping = {
            ".pdf":  "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc":  "application/msword",
        }
        return mapping.get(ext.lower(), "application/octet-stream")


# ─── Factory: Return correct handler based on config ──────────────────────────
def get_file_handler() -> LocalFileHandler | S3FileHandler:
    """
    Return the appropriate file handler based on configuration.
    Uses S3 if USE_S3=True, otherwise uses local filesystem.
    """
    if settings.USE_S3:
        logger.info("Using S3 file handler")
        return S3FileHandler()
    logger.info("Using local file handler")
    return LocalFileHandler()


# ─── Singleton ─────────────────────────────────────────────────────────────────
file_handler = get_file_handler()
