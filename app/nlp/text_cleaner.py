# app/nlp/text_cleaner.py

import re
import unicodedata
from app.utils.logger import get_logger
from app.utils import regex_patterns as patterns

logger = get_logger(__name__)


class TextCleaner:
    """
    Cleans and normalizes raw text extracted from PDFs.

    Handles:
      - Unicode normalization
      - Encoding artifacts (ligatures, smart quotes, etc.)
      - OCR noise characters
      - Excessive whitespace and newlines
      - Bullet point normalization
      - Common PDF extraction artifacts
    """

    # ─── Unicode Ligature Map ──────────────────────────────────────────────────
    LIGATURE_MAP = {
        "\ufb00": "ff",   "\ufb01": "fi",   "\ufb02": "fl",
        "\ufb03": "ffi",  "\ufb04": "ffl",  "\ufb05": "st",
        "\ufb06": "st",   "\u0132": "IJ",   "\u0133": "ij",
        "\u00e6": "ae",   "\u00c6": "AE",   "\u0153": "oe",
        "\u0152": "OE",
    }

    # ─── Smart Quote Map ───────────────────────────────────────────────────────
    QUOTE_MAP = {
        "\u2018": "'",    "\u2019": "'",    "\u201a": "'",
        "\u201b": "'",    "\u201c": '"',    "\u201d": '"',
        "\u201e": '"',    "\u201f": '"',    "\u2032": "'",
        "\u2033": '"',    "\u00ab": '"',    "\u00bb": '"',
    }

    # ─── Dash / Hyphen Normalization ───────────────────────────────────────────
    DASH_MAP = {
        "\u2013": "-",    # En dash
        "\u2014": "-",    # Em dash
        "\u2015": "-",    # Horizontal bar
        "\u2212": "-",    # Minus sign
        "\u2010": "-",    # Hyphen
        "\u2011": "-",    # Non-breaking hyphen
    }

    # ─── Bullet Point Normalization ────────────────────────────────────────────
    BULLET_MAP = {
        "\u2022": "-",    # •
        "\u2023": "-",    # ‣
        "\u25e6": "-",    # ◦
        "\u2043": "-",    # ⁃
        "\u204c": "-",    # ⁌
        "\u204d": "-",    # ⁍
        "\u2219": "-",    # ∙
        "\u25aa": "-",    # ▪
        "\u25ab": "-",    # ▫
        "\u25cf": "-",    # ●
        "\u25cb": "-",    # ○
        "\u25a0": "-",    # ■
        "\u25a1": "-",    # □
    }

    def __init__(self):
        # Combine all character maps
        self.char_map = {
            **self.LIGATURE_MAP,
            **self.QUOTE_MAP,
            **self.DASH_MAP,
            **self.BULLET_MAP,
        }

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def clean(
        self,
        text: str,
        aggressive: bool = False,
    ) -> str:
        """
        Full cleaning pipeline for extracted text.

        Args:
            text:       Raw text to clean
            aggressive: If True, also removes non-ASCII characters
                        (use for heavily noisy OCR output)

        Returns:
            Cleaned text string
        """
        if not text:
            return ""

        # Step 1: Unicode normalization (NFC form)
        text = unicodedata.normalize("NFC", text)

        # Step 2: Replace special characters
        text = self._replace_special_chars(text)

        # Step 3: Fix encoding artifacts
        text = self._fix_encoding_artifacts(text)

        # Step 4: Remove control characters
        text = patterns.CONTROL_CHARS.sub(" ", text)

        # Step 5: Normalize whitespace
        text = self._normalize_whitespace(text)

        # Step 6: Remove OCR noise
        text = self._remove_ocr_noise(text)

        # Step 7: Aggressive mode — strip non-ASCII
        if aggressive:
            text = patterns.NON_ASCII.sub(" ", text)
            text = self._normalize_whitespace(text)

        return text.strip()

    def clean_line(self, line: str) -> str:
        """Clean a single line of text."""
        line = self.clean(line)
        # Remove leading bullet/dash artifacts
        line = re.sub(r"^[\s\-•·▪►▸]+", "", line)
        return line.strip()

    def clean_lines(self, text: str) -> list[str]:
        """Split text into lines and clean each one."""
        lines = text.splitlines()
        cleaned = [self.clean_line(line) for line in lines]
        return [l for l in cleaned if l.strip()]

    # ─── Character Replacement ─────────────────────────────────────────────────
    def _replace_special_chars(self, text: str) -> str:
        """Replace known special characters with ASCII equivalents."""
        for char, replacement in self.char_map.items():
            text = text.replace(char, replacement)
        return text

    def _fix_encoding_artifacts(self, text: str) -> str:
        """
        Fix common PDF encoding artifacts:
          - Broken spaces (non-breaking, zero-width, etc.)
          - Repeated characters from bad encoding
        """
        # Non-breaking space → regular space
        text = text.replace("\u00a0", " ")
        text = text.replace("\u200b", "")   # Zero-width space
        text = text.replace("\u200c", "")   # Zero-width non-joiner
        text = text.replace("\u200d", "")   # Zero-width joiner
        text = text.replace("\ufeff", "")   # BOM
        text = text.replace("\u00ad", "")   # Soft hyphen

        # Fix common OCR substitutions
        # (these are conservative — only clear cases)
        text = re.sub(r"(?<=[a-z])l(?=[A-Z])", "I", text)   # l → I between words

        return text

    # ─── Whitespace Normalization ──────────────────────────────────────────────
    def _normalize_whitespace(self, text: str) -> str:
        """
        Normalize all whitespace:
          - Multiple spaces → single space
          - Multiple newlines → max 2 newlines
          - Tabs → spaces
        """
        # Tabs to spaces
        text = text.replace("\t", " ")

        # Multiple spaces to single
        text = patterns.MULTIPLE_SPACES.sub(" ", text)

        # Multiple newlines to max 2
        text = patterns.MULTIPLE_NEWLINES.sub("\n\n", text)

        return text

    # ─── OCR Noise Removal ─────────────────────────────────────────────────────
    def _remove_ocr_noise(self, text: str) -> str:
        """
        Remove common OCR noise patterns:
          - Isolated special characters on their own line
          - Lines with mostly non-alphanumeric characters
          - Very short garbled lines (1-2 random chars)
        """
        lines  = text.splitlines()
        clean  = []

        for line in lines:
            stripped = line.strip()

            # Skip empty lines (preserve structure)
            if not stripped:
                clean.append("")
                continue

            # Skip lines that are mostly noise
            if self._is_noise_line(stripped):
                logger.debug(f"Removed OCR noise line: '{stripped[:40]}'")
                continue

            clean.append(line)

        return "\n".join(clean)

    def _is_noise_line(self, text: str) -> bool:
        """
        Determine if a line is OCR noise.
        Returns True if line should be discarded.
        """
        if len(text) == 0:
            return False

        # Single character (non-alphanumeric)
        if len(text) == 1 and not text.isalnum():
            return True

        # Very short line with mostly symbols
        if len(text) <= 3:
            alnum_count = sum(1 for c in text if c.isalnum())
            if alnum_count == 0:
                return True

        # Line is >80% non-alphanumeric (excluding spaces)
        non_space = text.replace(" ", "")
        if len(non_space) > 0:
            alnum_ratio = sum(1 for c in non_space if c.isalnum()) / len(non_space)
            if alnum_ratio < 0.20 and len(text) < 10:
                return True

        return False

    # ─── Specific Cleaners ─────────────────────────────────────────────────────
    def normalize_bullets(self, text: str) -> str:
        """
        Normalize all bullet point styles to a standard dash (-).
        """
        for bullet_char in self.BULLET_MAP:
            text = text.replace(bullet_char, "- ")
        # Also normalize ASCII bullets
        text = re.sub(r"^[\s]*[*+>]\s+", "- ", text, flags=re.MULTILINE)
        return text

    def remove_urls(self, text: str) -> str:
        """Remove URLs from text (keep domain-only references)."""
        text = re.sub(
            r"https?://[^\s]+",
            "",
            text
        )
        return text.strip()

    def extract_clean_lines(
        self,
        text: str,
        min_length: int = 2,
    ) -> list[str]:
        """
        Extract non-empty, clean lines from text.

        Args:
            text:       Input text
            min_length: Minimum line length to keep

        Returns:
            List of clean, non-empty lines
        """
        cleaned = self.clean(text)
        lines = [
            line.strip()
            for line in cleaned.splitlines()
            if line.strip() and len(line.strip()) >= min_length
        ]
        return lines

    def normalize_section_text(self, text: str) -> str:
        """
        Normalize text for section header matching.
        Lowercase, strip punctuation, normalize spaces.
        """
        text = text.lower().strip()
        text = re.sub(r"[:\-_=*#~]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


# ─── Singleton ─────────────────────────────────────────────────────────────────
text_cleaner = TextCleaner()
