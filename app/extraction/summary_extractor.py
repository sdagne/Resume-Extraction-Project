# Profile summary / objective extraction
# app/extraction/summary_extractor.py

import re
from typing import Optional

from app.utils.logger import get_logger
from app.nlp.text_cleaner import text_cleaner
from app.utils import regex_patterns as patterns

logger = get_logger(__name__)

# ─── Min/Max Summary Length ────────────────────────────────────────────────────
MIN_SUMMARY_LENGTH = 30
MAX_SUMMARY_LENGTH = 1500


class SummaryExtractor:
    """
    Extracts the professional summary or objective statement
    from resume text.

    Handles:
      - Dedicated summary/objective/profile sections
      - Inline summaries at the top of the resume
      - Multi-paragraph summaries
    """

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def extract(
        self,
        section_text: str,
        full_text:    Optional[str] = None,
    ) -> Optional[str]:
        """
        Extract professional summary from section text.

        Args:
            section_text: Text from the summary/profile section
            full_text:    Full resume text (for fallback extraction)

        Returns:
            Clean summary string or None
        """
        # ── Primary: Use dedicated section text ───────────────────────────────
        if section_text and section_text.strip():
            summary = self._clean_summary(section_text)
            if summary and len(summary) >= MIN_SUMMARY_LENGTH:
                logger.info(f"Summary extracted: {len(summary)} chars")
                return summary

        # ── Fallback: Extract from top of full resume ──────────────────────────
        if full_text:
            summary = self._extract_from_top(full_text)
            if summary:
                logger.info(
                    f"Summary extracted from top of resume: "
                    f"{len(summary)} chars"
                )
                return summary

        logger.debug("No summary found")
        return None

    # ─── Summary Cleaning ──────────────────────────────────────────────────────
    def _clean_summary(self, text: str) -> Optional[str]:
        """
        Clean and normalize summary text.
        Removes section headers, excessive whitespace, and noise.
        """
        lines = text_cleaner.extract_clean_lines(text)
        if not lines:
            return None

        clean_lines = []
        for line in lines:
            # Skip section header lines
            if self._is_section_header(line):
                continue
            # Skip very short lines (likely noise)
            if len(line) < 10:
                continue
            # Skip lines that look like contact info
            if (
                patterns.EMAIL.search(line) or
                patterns.PHONE.search(line) or
                patterns.LINKEDIN.search(line)
            ):
                continue
            clean_lines.append(line)

        if not clean_lines:
            return None

        summary = " ".join(clean_lines)
        summary = re.sub(r"\s+", " ", summary).strip()

        # Truncate if too long
        if len(summary) > MAX_SUMMARY_LENGTH:
            summary = summary[:MAX_SUMMARY_LENGTH].rsplit(" ", 1)[0] + "..."

        return summary if len(summary) >= MIN_SUMMARY_LENGTH else None

    # ─── Top-of-Resume Extraction ──────────────────────────────────────────────
    def _extract_from_top(self, full_text: str) -> Optional[str]:
        """
        Extract summary from the top portion of the resume.
        Looks for a paragraph of 2+ sentences after the contact info.
        """
        lines = full_text.splitlines()
        summary_lines = []
        in_contact    = True
        found_start   = False

        for line in lines[:40]:  # Only check first 40 lines
            stripped = line.strip()
            if not stripped:
                if found_start and summary_lines:
                    break   # End of summary paragraph
                continue

            # Skip contact info lines
            if in_contact and (
                patterns.EMAIL.search(stripped) or
                patterns.PHONE.search(stripped) or
                patterns.LINKEDIN.search(stripped) or
                len(stripped.split()) <= 3
            ):
                continue
            else:
                in_contact = False

            # Skip section headers
            if self._is_section_header(stripped):
                if found_start:
                    break
                continue

            # Check if this looks like a summary sentence
            if len(stripped.split()) >= 8:
                found_start = True
                summary_lines.append(stripped)

        if not summary_lines:
            return None

        summary = " ".join(summary_lines)
        return summary if len(summary) >= MIN_SUMMARY_LENGTH else None

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _is_section_header(self, text: str) -> bool:
        """Check if text is a section header."""
        from app.utils.constants import SECTION_KEYWORDS
        normalized = text.lower().strip().rstrip(":")
        for keywords in SECTION_KEYWORDS.values():
            if normalized in [k.lower() for k in keywords]:
                return True
        if text.isupper() and len(text.split()) <= 4:
            return True
        return False


# ─── Singleton ─────────────────────────────────────────────────────────────────
summary_extractor = SummaryExtractor()
