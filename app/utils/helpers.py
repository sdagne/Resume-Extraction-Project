# app/utils/helpers.py

import re
import uuid
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

from app.utils.constants import PRESENT_KEYWORDS, MONTH_ABBREVIATIONS
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ─── ID & File Helpers ─────────────────────────────────────────────────────────

def generate_uuid() -> str:
    """Generate a unique UUID string."""
    return str(uuid.uuid4())


def generate_file_hash(file_bytes: bytes) -> str:
    """Generate MD5 hash of file content for deduplication."""
    return hashlib.md5(file_bytes).hexdigest()


def get_file_extension(filename: str) -> str:
    """Return lowercase file extension including the dot."""
    return Path(filename).suffix.lower()


def sanitize_filename(filename: str) -> str:
    """Remove unsafe characters from filename."""
    name = Path(filename).stem
    name = re.sub(r"[^\w\s\-]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name[:100]  # Limit length


def build_export_filename(base_name: str, extension: str) -> str:
    """Build a timestamped export filename."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{sanitize_filename(base_name)}_{timestamp}.{extension.lstrip('.')}"


# ─── Text Helpers ──────────────────────────────────────────────────────────────

def normalize_whitespace(text: str) -> str:
    """Replace multiple spaces and newlines with single ones."""
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_empty(value: Any) -> bool:
    """Check if a value is None, empty string, or empty collection."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict, set)):
        return len(value) == 0
    return False


def truncate_text(text: str, max_length: int = 500) -> str:
    """Truncate text to max_length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3].rstrip() + "..."


def split_into_lines(text: str) -> list[str]:
    """Split text into non-empty, stripped lines."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def is_likely_header(text: str, font_size: float = 0.0, is_bold: bool = False) -> bool:
    """
    Heuristic to determine if a text line is likely a section header.
    Uses font size, bold style, and text pattern analysis.
    """
    text = text.strip()
    if not text or len(text) > 60:
        return False

    # Font-based signals
    if font_size >= 12.0 or is_bold:
        return True

    # Pattern-based signals
    if text.isupper() and len(text) > 2:
        return True
    if text.endswith(":") and len(text.split()) <= 5:
        return True

    return False


# ─── Date Helpers ──────────────────────────────────────────────────────────────

def is_present_date(text: str) -> bool:
    """Check if a date string means 'current / present'."""
    return text.strip().lower() in PRESENT_KEYWORDS


def expand_month_abbreviation(month: str) -> str:
    """Convert 'Jan' → 'January', etc."""
    return MONTH_ABBREVIATIONS.get(month.lower()[:3], month)


def calculate_duration_years(
    start_str: Optional[str],
    end_str: Optional[str]
) -> Optional[float]:
    """
    Calculate duration in years between two date strings.
    Returns None if dates cannot be parsed.
    """
    from app.nlp.date_parser import parse_date_string

    try:
        start = parse_date_string(start_str)
        end = datetime.now() if is_present_date(end_str or "") else parse_date_string(end_str)

        if start and end:
            delta = end - start
            return round(delta.days / 365.25, 1)
    except Exception as e:
        logger.debug(f"Duration calculation failed: {e}")
    return None


# ─── List Helpers ──────────────────────────────────────────────────────────────

def deduplicate(items: list) -> list:
    """Remove duplicates while preserving order."""
    seen = set()
    result = []
    for item in items:
        key = item.lower() if isinstance(item, str) else str(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def flatten(nested: list[list]) -> list:
    """Flatten a list of lists into a single list."""
    return [item for sublist in nested for item in sublist]


def chunk_list(lst: list, size: int) -> list[list]:
    """Split a list into chunks of given size."""
    return [lst[i:i + size] for i in range(0, len(lst), size)]


# ─── JSON Helpers ──────────────────────────────────────────────────────────────

def safe_get(data: dict, *keys, default=None) -> Any:
    """Safely get nested dict value."""
    for key in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(key, default)
    return data


def remove_empty_fields(data: dict) -> dict:
    """Recursively remove None and empty fields from a dict."""
    cleaned = {}
    for key, value in data.items():
        if isinstance(value, dict):
            nested = remove_empty_fields(value)
            if nested:
                cleaned[key] = nested
        elif isinstance(value, list):
            cleaned_list = [
                remove_empty_fields(v) if isinstance(v, dict) else v
                for v in value
                if not is_empty(v)
            ]
            if cleaned_list:
                cleaned[key] = cleaned_list
        elif not is_empty(value):
            cleaned[key] = value
    return cleaned
