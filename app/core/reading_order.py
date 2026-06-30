# app/core/reading_order.py

from app.utils.logger import get_logger
from app.utils import regex_patterns as patterns

logger = get_logger(__name__)


class ReadingOrderReconstructor:
    """
    Reconstructs the logical reading order of text blocks
    after layout analysis and column separation.

    Handles:
      - Removing page numbers, headers, footers
      - Merging split lines (hyphenated words, wrapped text)
      - Normalizing section separators
      - Removing duplicate content (e.g., repeated page headers)
    """

    def __init__(self):
        self.seen_texts = set()   # For deduplication across pages

    def reconstruct(
        self,
        ordered_blocks: list[dict],
        remove_page_numbers: bool = True,
        merge_split_lines:   bool = True,
        deduplicate:         bool = True,
    ) -> str:
        """
        Take ordered blocks and produce clean, logical text.

        Args:
            ordered_blocks:      Blocks in reading order (from LayoutAnalyzer)
            remove_page_numbers: Strip page number lines
            merge_split_lines:   Merge hyphenated line breaks
            deduplicate:         Remove repeated lines across pages

        Returns:
            Clean text string with logical reading order
        """
        if not ordered_blocks:
            return ""

        lines = []
        self.seen_texts.clear()

        for block in ordered_blocks:
            text = block.get("text", "").strip()
            if not text:
                continue

            # ── Remove page numbers ───────────────────────────────────────────
            if remove_page_numbers and self._is_page_number(text):
                logger.debug(f"Removed page number: '{text}'")
                continue

            # ── Remove section dividers ───────────────────────────────────────
            if self._is_divider(text):
                lines.append("")   # Keep as blank line separator
                continue

            # ── Deduplicate ───────────────────────────────────────────────────
            if deduplicate:
                normalized = text.lower().strip()
                if normalized in self.seen_texts:
                    logger.debug(f"Skipped duplicate: '{text[:40]}'")
                    continue
                self.seen_texts.add(normalized)

            lines.append(text)

        # ── Merge split lines ──────────────────────────────────────────────────
        if merge_split_lines:
            lines = self._merge_hyphenated_lines(lines)

        # ── Clean up blank lines ───────────────────────────────────────────────
        lines = self._clean_blank_lines(lines)

        return "\n".join(lines)

    # ─── Line Filters ──────────────────────────────────────────────────────────
    def _is_page_number(self, text: str) -> bool:
        """Detect standalone page number lines."""
        return bool(patterns.PAGE_NUMBER.match(text.strip()))

    def _is_divider(self, text: str) -> bool:
        """Detect visual separator lines (---, ===, ...)."""
        return bool(patterns.SECTION_DIVIDER.match(text.strip()))

    def _is_footer_header(self, text: str, threshold: int = 30) -> bool:
        """
        Detect repeated short lines that are likely page headers/footers.
        (Checked via deduplication — if seen on multiple pages → likely header/footer)
        """
        return len(text) < threshold and text in self.seen_texts

    # ─── Line Merging ──────────────────────────────────────────────────────────
    def _merge_hyphenated_lines(self, lines: list[str]) -> list[str]:
        """
        Merge lines that were split with a hyphen at line break.
        Example:
            "compre-"  +  "hensive"  →  "comprehensive"
        """
        if not lines:
            return lines

        merged = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Check if line ends with hyphen and next line exists
            if (
                line.endswith("-")
                and i + 1 < len(lines)
                and lines[i + 1]
                and not lines[i + 1][0].isupper()  # Next line starts lowercase
            ):
                merged.append(line[:-1] + lines[i + 1])
                i += 2
            else:
                merged.append(line)
                i += 1

        return merged

    def _clean_blank_lines(self, lines: list[str]) -> list[str]:
        """
        Remove excessive blank lines (max 1 consecutive blank line).
        """
        result      = []
        blank_count = 0

        for line in lines:
            if not line.strip():
                blank_count += 1
                if blank_count <= 1:
                    result.append("")
            else:
                blank_count = 0
                result.append(line)

        # Strip leading/trailing blank lines
        while result and not result[0].strip():
            result.pop(0)
        while result and not result[-1].strip():
            result.pop()

        return result

    # ─── Block-Level Utilities ─────────────────────────────────────────────────
    def filter_noise_blocks(self, blocks: list[dict]) -> list[dict]:
        """
        Filter out noise blocks before reconstruction:
          - Very short single-character blocks
          - Blocks containing only special characters
          - Blocks that are just whitespace
        """
        clean = []
        for block in blocks:
            text = block.get("text", "").strip()
            if not text:
                continue
            if len(text) <= 1 and not text.isalnum():
                continue
            if all(not c.isalnum() for c in text):
                continue
            clean.append(block)
        return clean

    def assign_reading_weights(
        self,
        blocks: list[dict],
        page_height: float,
    ) -> list[dict]:
        """
        Assign a reading order weight to each block.
        Lower weight = read first.

        Weight formula:
            weight = (page_num * 10000) + (y_band * 100) + column_offset
        """
        for block in blocks:
            page_num = block.get("page_num",  1)
            y0       = block["bbox"].get("y0", 0)
            column   = block.get("column", "full")

            # Y band (group into 10px bands)
            y_band = int(y0 / 10)

            # Column offset: left=0, full=0, right=1
            col_offset = 1 if column == "right" else 0

            block["reading_weight"] = (
                (page_num - 1) * 100000 +
                y_band * 10 +
                col_offset
            )

        return blocks

    def sort_by_weight(self, blocks: list[dict]) -> list[dict]:
        """Sort blocks by their assigned reading weight."""
        return sorted(
            blocks,
            key=lambda b: b.get("reading_weight", 0)
        )


# ─── Singleton ─────────────────────────────────────────────────────────────────
reading_order_reconstructor = ReadingOrderReconstructor()
