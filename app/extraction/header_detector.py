# app/extraction/header_detector.py

import re
from typing import Optional

from app.utils.constants import FontSize
from app.utils.logger import get_logger
from app.utils import regex_patterns as patterns

logger = get_logger(__name__)


class HeaderDetector:
    """
    Detects section headers within a resume using multiple signals:
      - Font size analysis
      - Bold / italic styling
      - Text pattern analysis (ALL CAPS, short lines, colon-ending)
      - Positional analysis (relative to page)
      - Visual separator detection

    Provides confidence scores for each detection.
    """

    # ─── Confidence Weights ────────────────────────────────────────────────────
    WEIGHT_FONT_SIZE   = 0.35
    WEIGHT_BOLD        = 0.25
    WEIGHT_ALL_CAPS    = 0.20
    WEIGHT_SHORT_TEXT  = 0.10
    WEIGHT_ENDS_COLON  = 0.10

    def __init__(self):
        self.header_threshold = 0.45   # Minimum confidence to classify as header

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def is_header(
        self,
        text:      str,
        font_size: float = 0.0,
        is_bold:   bool  = False,
        y0:        float = 0.0,
        page_height: float = 0.0,
    ) -> dict:
        """
        Determine if a text block is a section header.

        Returns:
            {
                "is_header":  bool,
                "confidence": float,
                "signals":    dict,   # Which signals fired
            }
        """
        text = text.strip()
        if not text or len(text) > 80:
            return {"is_header": False, "confidence": 0.0, "signals": {}}

        signals    = {}
        confidence = 0.0

        # ── Signal 1: Font size ────────────────────────────────────────────────
        font_signal = self._score_font_size(font_size)
        signals["font_size"] = font_signal
        confidence += font_signal * self.WEIGHT_FONT_SIZE

        # ── Signal 2: Bold ────────────────────────────────────────────────────
        bold_signal = 1.0 if is_bold else 0.0
        signals["is_bold"] = bold_signal
        confidence += bold_signal * self.WEIGHT_BOLD

        # ── Signal 3: ALL CAPS ────────────────────────────────────────────────
        caps_signal = self._score_caps(text)
        signals["all_caps"] = caps_signal
        confidence += caps_signal * self.WEIGHT_ALL_CAPS

        # ── Signal 4: Short text ──────────────────────────────────────────────
        short_signal = self._score_length(text)
        signals["short_text"] = short_signal
        confidence += short_signal * self.WEIGHT_SHORT_TEXT

        # ── Signal 5: Ends with colon ─────────────────────────────────────────
        colon_signal = 1.0 if text.endswith(":") else 0.0
        signals["ends_colon"] = colon_signal
        confidence += colon_signal * self.WEIGHT_ENDS_COLON

        # ── Penalty: Contains email/phone/URL ─────────────────────────────────
        if (
            patterns.EMAIL.search(text) or
            patterns.PHONE.search(text) or
            patterns.DATE_RANGE.search(text)
        ):
            confidence *= 0.1   # Strong penalty

        # ── Penalty: Too many words ────────────────────────────────────────────
        word_count = len(text.split())
        if word_count > 6:
            confidence *= max(0.2, 1 - (word_count - 6) * 0.1)

        is_hdr = confidence >= self.header_threshold

        return {
            "is_header":  is_hdr,
            "confidence": round(confidence, 3),
            "signals":    signals,
        }

    def detect_name_block(
        self,
        text_blocks: list[dict],
        top_n_blocks: int = 5,
    ) -> Optional[dict]:
        """
        Detect the block most likely containing the candidate's name.
        The name is typically:
          - In the first few blocks
          - Has the largest font size on the page
          - Is short (1–4 words)
          - Not an email, phone, or URL
        """
        if not text_blocks:
            return None

        # Only look at top N blocks
        candidates = text_blocks[:top_n_blocks]

        scored = []
        for block in candidates:
            text      = block.get("text", "").strip()
            font_size = block.get("font_size", 0.0)

            if not text or len(text) > 60:
                continue

            # Disqualify if contains contact info
            if (
                patterns.EMAIL.search(text) or
                patterns.PHONE.search(text) or
                patterns.LINKEDIN.search(text)
            ):
                continue

            # Disqualify if looks like a section header keyword
            if self._is_section_keyword(text):
                continue

            word_count = len(text.split())
            if word_count < 1 or word_count > 5:
                continue

            # Score based on font size and position
            score = font_size * 0.6 + (5 - word_count) * 2
            scored.append({"block": block, "score": score})

        if not scored:
            return None

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[0]["block"]

    def find_all_headers(
        self,
        text_blocks: list[dict],
    ) -> list[dict]:
        """
        Find all section header blocks in a list of text blocks.

        Returns list of blocks identified as headers with confidence scores.
        """
        headers = []
        for block in text_blocks:
            result = self.is_header(
                text      = block.get("text", ""),
                font_size = block.get("font_size", 0.0),
                is_bold   = block.get("is_bold",   False),
            )
            if result["is_header"]:
                headers.append({
                    **block,
                    "header_confidence": result["confidence"],
                    "header_signals":    result["signals"],
                })
        return headers

    def get_dominant_font_size(
        self,
        text_blocks: list[dict],
    ) -> float:
        """
        Find the most common (dominant) font size in the document.
        Used to identify body text font size for relative comparison.
        """
        from collections import Counter
        sizes = [
            round(b.get("font_size", 0.0))
            for b in text_blocks
            if b.get("font_size", 0.0) > 0
        ]
        if not sizes:
            return 11.0
        counter = Counter(sizes)
        return float(counter.most_common(1)[0][0])

    # ─── Scoring Helpers ───────────────────────────────────────────────────────
    def _score_font_size(self, font_size: float) -> float:
        """
        Score font size signal.
        Returns 0.0–1.0 based on how large the font is.
        """
        if font_size <= 0:
            return 0.0
        if font_size >= FontSize.NAME_MIN:
            return 1.0
        if font_size >= FontSize.SECTION_HEADER_MIN:
            return 0.8
        if font_size >= 11.0:
            return 0.3
        return 0.0

    def _score_caps(self, text: str) -> float:
        """
        Score ALL CAPS signal.
        Returns 1.0 if all alpha chars are uppercase.
        """
        alpha = [c for c in text if c.isalpha()]
        if not alpha:
            return 0.0
        upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
        return upper_ratio if upper_ratio >= 0.85 else 0.0

    def _score_length(self, text: str) -> float:
        """
        Score text length signal.
        Short texts (1–4 words) are more likely to be headers.
        """
        words = len(text.split())
        if words <= 2:
            return 1.0
        if words <= 4:
            return 0.7
        if words <= 6:
            return 0.3
        return 0.0

    def _is_section_keyword(self, text: str) -> bool:
        """Check if text matches a known section keyword."""
        from app.utils.constants import SECTION_KEYWORDS
        normalized = text.lower().strip().rstrip(":")
        for keywords in SECTION_KEYWORDS.values():
            if normalized in [k.lower() for k in keywords]:
                return True
        return False


# ─── Singleton ─────────────────────────────────────────────────────────────────
header_detector = HeaderDetector()
