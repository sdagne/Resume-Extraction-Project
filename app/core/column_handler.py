# app/core/column_handler.py

from app.utils.logger import get_logger
from app.utils.helpers import normalize_whitespace

logger = get_logger(__name__)


class ColumnHandler:
    """
    Handles multi-column text reconstruction.

    The core problem: when you extract text from a two-column PDF
    naively, lines from column 1 and column 2 get interleaved,
    producing garbled output like:

        "Software Engineer   |  Python Django React"
        "at Google           |  PostgreSQL Docker AWS"

    This class separates columns and reconstructs them correctly.
    """

    def __init__(self, column_gap_threshold: float = 0.10):
        """
        Args:
            column_gap_threshold: Minimum relative gap (as fraction of
                                  page width) to consider two blocks
                                  as being in different columns.
        """
        self.column_gap_threshold = column_gap_threshold

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def reconstruct(
        self,
        text_blocks: list[dict],
        page_width:  float,
        column_boundary: float,
        layout_type: str = "two_column",
    ) -> str:
        """
        Reconstruct correctly ordered text from multi-column blocks.

        Args:
            text_blocks:      List of block dicts with bbox info
            page_width:       Page width in points
            column_boundary:  X position splitting left/right columns
            layout_type:      Layout type from LayoutAnalyzer

        Returns:
            Clean reconstructed text string
        """
        if not text_blocks:
            return ""

        if layout_type == "single_column":
            return self._reconstruct_single(text_blocks)

        elif layout_type == "two_column":
            return self._reconstruct_two_column(
                text_blocks, column_boundary
            )

        elif layout_type == "sidebar":
            return self._reconstruct_sidebar(
                text_blocks, column_boundary, page_width
            )

        else:
            return self._reconstruct_adaptive(text_blocks, page_width)

    # ─── Single Column ─────────────────────────────────────────────────────────
    def _reconstruct_single(self, blocks: list[dict]) -> str:
        """Simple top-to-bottom reconstruction for single column."""
        sorted_blocks = sorted(
            blocks,
            key=lambda b: (b["bbox"].get("y0", 0), b["bbox"].get("x0", 0))
        )
        return normalize_whitespace(
            "\n".join(b["text"] for b in sorted_blocks if b.get("text"))
        )

    # ─── Two Column ────────────────────────────────────────────────────────────
    def _reconstruct_two_column(
        self,
        blocks: list[dict],
        column_boundary: float,
    ) -> str:
        """
        Reconstruct two-column layout.
        Reads left column completely, then right column.
        Full-width blocks are inserted at their natural position.
        """
        left_blocks  = []
        right_blocks = []
        full_blocks  = []

        for block in blocks:
            bbox = block.get("bbox", {})
            x0   = bbox.get("x0", 0)
            x1   = bbox.get("x1", 0)

            block_width = x1 - x0
            if block_width > column_boundary * 0.85:
                full_blocks.append(block)
            elif x0 < column_boundary:
                left_blocks.append(block)
            else:
                right_blocks.append(block)

        # Sort each column by Y
        left_blocks.sort( key=lambda b: b["bbox"].get("y0", 0))
        right_blocks.sort(key=lambda b: b["bbox"].get("y0", 0))
        full_blocks.sort( key=lambda b: b["bbox"].get("y0", 0))

        # Build text sections
        sections = []

        # Add full-width blocks that appear before columns
        if full_blocks:
            first_col_y = min(
                (b["bbox"].get("y0", 9999) for b in left_blocks + right_blocks),
                default=0
            )
            pre_blocks = [b for b in full_blocks if b["bbox"].get("y0", 0) < first_col_y]
            post_blocks = [b for b in full_blocks if b["bbox"].get("y0", 0) >= first_col_y]

            for b in pre_blocks:
                sections.append(b["text"])

        # Left column
        if left_blocks:
            sections.append("\n".join(b["text"] for b in left_blocks))

        # Right column
        if right_blocks:
            sections.append("\n".join(b["text"] for b in right_blocks))

        # Post full-width blocks
        for b in full_blocks:
            if b not in (pre_blocks if full_blocks else []):
                sections.append(b["text"])

        return normalize_whitespace("\n\n".join(filter(None, sections)))

    # ─── Sidebar ───────────────────────────────────────────────────────────────
    def _reconstruct_sidebar(
        self,
        blocks: list[dict],
        column_boundary: float,
        page_width: float,
    ) -> str:
        """
        Reconstruct sidebar layout.
        Determines which side is the sidebar (narrower) and
        puts main content first.
        """
        left_blocks  = []
        right_blocks = []

        for block in blocks:
            x0 = block["bbox"].get("x0", 0)
            if x0 < column_boundary:
                left_blocks.append(block)
            else:
                right_blocks.append(block)

        left_blocks.sort( key=lambda b: b["bbox"].get("y0", 0))
        right_blocks.sort(key=lambda b: b["bbox"].get("y0", 0))

        # Determine which is the sidebar (narrower column)
        left_width  = column_boundary
        right_width = page_width - column_boundary

        if left_width < right_width:
            # Left is sidebar → main content is right
            main_text    = "\n".join(b["text"] for b in right_blocks)
            sidebar_text = "\n".join(b["text"] for b in left_blocks)
        else:
            # Right is sidebar → main content is left
            main_text    = "\n".join(b["text"] for b in left_blocks)
            sidebar_text = "\n".join(b["text"] for b in right_blocks)

        combined = "\n\n".join(filter(None, [main_text, sidebar_text]))
        return normalize_whitespace(combined)

    # ─── Adaptive ──────────────────────────────────────────────────────────────
    def _reconstruct_adaptive(
        self,
        blocks: list[dict],
        page_width: float,
    ) -> str:
        """
        Adaptive reconstruction for mixed/unknown layouts.
        Groups blocks into rows and reconstructs left-to-right per row.
        """
        if not blocks:
            return ""

        # Group into horizontal rows
        row_tolerance = 15   # pixels
        rows = self._group_into_rows(blocks, row_tolerance)

        lines = []
        for row in rows:
            # Sort row left-to-right
            row.sort(key=lambda b: b["bbox"].get("x0", 0))
            row_text = "  ".join(
                b["text"].strip()
                for b in row
                if b.get("text", "").strip()
            )
            if row_text:
                lines.append(row_text)

        return normalize_whitespace("\n".join(lines))

    def _group_into_rows(
        self,
        blocks: list[dict],
        tolerance: float,
    ) -> list[list[dict]]:
        """
        Group blocks that share approximately the same Y position
        into horizontal rows.
        """
        if not blocks:
            return []

        sorted_blocks = sorted(
            blocks,
            key=lambda b: b["bbox"].get("y0", 0)
        )

        rows  = []
        used  = set()

        for i, block in enumerate(sorted_blocks):
            if i in used:
                continue

            y0  = block["bbox"].get("y0", 0)
            row = [block]
            used.add(i)

            for j, other in enumerate(sorted_blocks):
                if j in used:
                    continue
                other_y0 = other["bbox"].get("y0", 0)
                if abs(other_y0 - y0) <= tolerance:
                    row.append(other)
                    used.add(j)

            rows.append(row)

        return rows

    # ─── Word-Level Reconstruction ─────────────────────────────────────────────
    def reconstruct_from_words(
        self,
        words: list[dict],
        page_width: float,
        column_boundary: float,
    ) -> str:
        """
        Reconstruct text from individual word positions.
        More accurate than block-level for complex layouts.

        Args:
            words: List of {"text", "x0", "y0", "x1", "y1", "page_num"}
        """
        if not words:
            return ""

        # Separate into columns
        left_words  = [w for w in words if w["x0"] < column_boundary]
        right_words = [w for w in words if w["x0"] >= column_boundary]

        def words_to_text(word_list: list[dict]) -> str:
            """Convert sorted word list to text with line breaks."""
            if not word_list:
                return ""

            sorted_words = sorted(word_list, key=lambda w: (
                round(w["y0"] / 10),  # Group within 10px rows
                w["x0"]
            ))

            lines = []
            current_line = []
            current_y = None

            for word in sorted_words:
                y0 = round(word["y0"] / 10) * 10
                if current_y is None or abs(y0 - current_y) <= 10:
                    current_line.append(word["text"])
                    current_y = y0
                else:
                    if current_line:
                        lines.append(" ".join(current_line))
                    current_line = [word["text"]]
                    current_y = y0

            if current_line:
                lines.append(" ".join(current_line))

            return "\n".join(lines)

        left_text  = words_to_text(left_words)
        right_text = words_to_text(right_words)

        combined = "\n\n".join(filter(None, [left_text, right_text]))
        return normalize_whitespace(combined)


# ─── Singleton ─────────────────────────────────────────────────────────────────
column_handler = ColumnHandler()
