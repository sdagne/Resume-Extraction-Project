
# app/models/__init__.py

from app.models.resume import Resume
from app.models.candidate import Candidate
from app.models.extraction_log import ExtractionLog

__all__ = [
    "Resume",
    "Candidate",
    "ExtractionLog",
]
