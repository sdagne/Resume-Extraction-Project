# app/security/audit_logger.py

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Audit log lives in its own file, separate from the app log
_AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "audit.jsonl"


def _write(record: dict) -> None:
    """Append one JSON line to the audit log file."""
    try:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        # Never let audit-log failures break the main request
        logger.warning(f"Audit log write failed: {e}")


def log_upload(
    *,
    client_ip: str,
    filename: str,
    size_bytes: int,
    is_suspicious: bool = False,
    api_key_hint: Optional[str] = None,
) -> None:
    _write({
        "event":         "file_upload",
        "ts":            datetime.now(timezone.utc).isoformat(),
        "client_ip":     client_ip,
        "filename":      filename,
        "size_bytes":    size_bytes,
        "is_suspicious": is_suspicious,
        "api_key_hint":  api_key_hint[:8] + "..." if api_key_hint else None,
    })


def log_extraction(
    *,
    client_ip: str,
    resume_id: str,
    status: str,
    duration_s: float,
    api_key_hint: Optional[str] = None,
) -> None:
    _write({
        "event":        "extraction",
        "ts":           datetime.now(timezone.utc).isoformat(),
        "client_ip":    client_ip,
        "resume_id":    str(resume_id),
        "status":       status,
        "duration_s":   round(duration_s, 3),
        "api_key_hint": api_key_hint[:8] + "..." if api_key_hint else None,
    })


def log_security_event(
    *,
    client_ip: str,
    event_type: str,
    detail: str,
) -> None:
    _write({
        "event":      "security",
        "ts":         datetime.now(timezone.utc).isoformat(),
        "client_ip":  client_ip,
        "event_type": event_type,
        "detail":     detail,
    })
