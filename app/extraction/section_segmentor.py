# app/extraction/section_segmentor.py

import re
from typing import Optional

from app.utils.constants import SectionName, SECTION_KEYWORDS, FontSize
from app.utils.logger import get_logger
from app.utils import regex_patterns as patterns
from app.nlp.text_cleaner import text_cleaner

logger = get_logger(__name__)


class SectionSegmentor:
    """
    Splits a resume's text blocks into labeled sections.

    Strategy (in priority order):
      1. Font-size / bold signals  → strong header indicator
      2. ALL-CAPS text             → likely section header
      3. Keyword matching          → match against known section keywords
      4. Positional heuristics     → top-of-page = contact section
      5. Fallback                  → assign to previous section

    Input:  List of text blocks from DigitalPDFParser or OCRParser
    Output: Dict mapping section names → list of text blocks
    """

    def __init__(self):
        # Build a flat keyword → section lookup for fast matching
        self._keyword_map = self._build_keyword_map()

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def segment(
        self,
        text_blocks: list[dict],
        page_height: float = 0.0,
    ) -> dict[str, list[dict]]:
        """
        Segment text blocks into resume sections.

        Args:
            text_blocks:  Ordered list of text block dicts
            page_height:  Page height for positional heuristics

        Returns:
            Dict of section_name → list of blocks belonging to that section
        """
        if not text_blocks:
            return {name: [] for name in SectionName.ALL}

        sections: dict[str, list[dict]] = {
            name: [] for name in SectionName.ALL
        }
        sections[SectionName.UNKNOWN] = []

        current_section = SectionName.CONTACT  # Default: start with contact
        header_candidates = []

        for i, block in enumerate(text_blocks):
            text       = block.get("text", "").strip()
            font_size  = block.get("font_size",  0.0)
            is_bold    = block.get("is_bold",    False)
            is_header  = block.get("is_header",  False)
            y0         = block.get("bbox", {}).get("y0", 0)

            if not text:
                continue

            # ── Check if this block is a section header ────────────────────
            detected_section = self._detect_section_header(
                text       = text,
                font_size  = font_size,
                is_bold    = is_bold,
                is_header  = is_header,
                y0         = y0,
                page_height= page_height,
                block_index= i,
                total_blocks=len(text_blocks),
            )

            if detected_section:
                current_section = detected_section
                # Mark block as a section header
                block["detected_section"] = detected_section
                block["is_section_header"]= True
                header_candidates.append({
                    "section": detected_section,
                    "text":    text,
                    "index":   i,
                })
                logger.debug(
                    f"Section detected: '{detected_section}' "
                    f"from text: '{text[:40]}'"
                )
            else:
                # Assign block to current section
                block["detected_section"]  = current_section
                block["is_section_header"] = False
                sections[current_section].append(block)

        logger.info(
            f"Segmentation complete: "
            + ", ".join(
                f"{k}={len(v)}"
                for k, v in sections.items()
                if v
            )
        )
        return sections

    def segment_from_text(self, full_text: str) -> dict[str, str]:
        """
        Segment plain text (not blocks) into sections.
        Used as a fallback when block-level data is unavailable.

        Returns:
            Dict of section_name → section text string
        """
        lines   = full_text.splitlines()
        result  = {name: [] for name in SectionName.ALL}
        result[SectionName.UNKNOWN] = []

        current = SectionName.CONTACT

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            section = self._match_keyword(stripped)
            if section and self._looks_like_header(stripped):
                current = section
            else:
                result[current].append(stripped)

        # Join each section's lines into a string
        return {
            name: "\n".join(lines_list)
            for name, lines_list in result.items()
        }

    # ─── Header Detection ──────────────────────────────────────────────────────
    def _detect_section_header(
        self,
        text:         str,
        font_size:    float,
        is_bold:      bool,
        is_header:    bool,
        y0:           float,
        page_height:  float,
        block_index:  int,
        total_blocks: int,
    ) -> Optional[str]:
        """
        Determine if a text block is a section header.
        Returns section name if it is, None otherwise.
        """
        # ── Pre-filter: Too long to be a header ───────────────────────────────
        if len(text) > 80:
            return None

        # ── Pre-filter: Looks like a date range ───────────────────────────────
        if patterns.DATE_RANGE.search(text):
            return None

        # ── Pre-filter: Looks like a URL or email ─────────────────────────────
        if patterns.EMAIL.search(text) or patterns.LINKEDIN.search(text):
            return None

        # ── Signal 1: Parser already flagged as header ────────────────────────
        if is_header:
            section = self._match_keyword(text)
            if section:
                return section

        # ── Signal 2: Large font size ─────────────────────────────────────────
        if font_size >= FontSize.SECTION_HEADER_MIN:
            section = self._match_keyword(text)
            if section:
                return section

        # ── Signal 3: Bold text ───────────────────────────────────────────────
        if is_bold:
            section = self._match_keyword(text)
            if section:
                return section

        # ── Signal 4: ALL CAPS text ───────────────────────────────────────────
        if self._is_all_caps(text):
            section = self._match_keyword(text)
            if section:
                return section
            # Even if no keyword match, ALL CAPS short text might be a header
            if len(text.split()) <= 4:
                section = self._match_keyword_fuzzy(text)
                if section:
                    return section

        # ── Signal 5: Ends with colon (common header style) ───────────────────
        if text.endswith(":"):
            clean = text[:-1].strip()
            section = self._match_keyword(clean)
            if section:
                return section

        # ── Signal 6: Pure keyword match (even without font signals) ──────────
        section = self._match_keyword(text)
        if section and len(text.split()) <= 5:
            return section

        return None

    # ─── Keyword Matching ──────────────────────────────────────────────────────
    def _match_keyword(self, text: str) -> Optional[str]:
        """
        Match text against known section keywords.
        Returns section name or None.
        """
        normalized = text_cleaner.normalize_section_text(text)

        # Exact match first
        if normalized in self._keyword_map:
            return self._keyword_map[normalized]

        # Partial match: check if normalized text contains a keyword
        for keyword, section in self._keyword_map.items():
            if keyword in normalized and len(keyword) > 4:
                return section

        return None

    def _match_keyword_fuzzy(self, text: str) -> Optional[str]:
        """
        Fuzzy keyword matching using simple edit distance.
        Used for ALL CAPS headers with minor typos.
        """
        from rapidfuzz import process, fuzz

        normalized = text_cleaner.normalize_section_text(text)
        keywords   = list(self._keyword_map.keys())

        match = process.extractOne(
            normalized,
            keywords,
            scorer=fuzz.ratio,
            score_cutoff=75,
        )

        if match:
            matched_keyword = match[0]
            return self._keyword_map[matched_keyword]

        return None

    def _build_keyword_map(self) -> dict[str, str]:
        """
        Build flat keyword → section_name lookup dict.
        """
        keyword_map = {}
        for section, keywords in SECTION_KEYWORDS.items():
            for keyword in keywords:
                normalized = text_cleaner.normalize_section_text(keyword)
                keyword_map[normalized] = section
        return keyword_map

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _is_all_caps(self, text: str) -> bool:
        """Check if text is all uppercase (ignoring spaces/punctuation)."""
        alpha_chars = [c for c in text if c.isalpha()]
        if not alpha_chars:
            return False
        return all(c.isupper() for c in alpha_chars) and len(alpha_chars) >= 3

    def _looks_like_header(self, text: str) -> bool:
        """
        Lightweight check: does this line look like a header?
        Used for plain-text segmentation.
        """
        if len(text) > 60:
            return False
        if self._is_all_caps(text):
            return True
        if text.endswith(":") and len(text.split()) <= 5:
            return True
        return False

    def get_section_text(
        self,
        sections: dict[str, list[dict]],
        section_name: str,
    ) -> str:
        """
        Extract plain text from a section's blocks.
        """
        blocks = sections.get(section_name, [])
        return "\n".join(
            b.get("text", "").strip()
            for b in blocks
            if b.get("text", "").strip()
        )

    def get_detected_sections(
        self,
        sections: dict[str, list[dict]],
    ) -> list[str]:
        """Return list of section names that have content."""
        return [
            name for name, blocks in sections.items()
            if blocks and name != SectionName.UNKNOWN
        ]


# ─── Singleton ─────────────────────────────────────────────────────────────────
section_segmentor = SectionSegmentor()
