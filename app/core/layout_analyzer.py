# app/core/layout_analyzer.py

from pathlib import Path
from typing import Optional
import numpy as np

from app.config import settings
from app.utils.logger import get_logger
from app.utils.constants import SectionName

logger = get_logger(__name__)


class LayoutAnalyzer:
    """
    Analyzes the spatial layout of extracted text blocks to:
      - Identify document regions (header, body, sidebar, footer)
      - Detect layout type (single-column, two-column, mixed)
      - Group blocks into logical zones
      - Assign reading order weights
      - Detect visual separators between sections

    Works on the output of DigitalPDFParser or OCRParser (text_blocks).
    No ML model needed — pure geometric + heuristic analysis.
    """

    # ─── Layout Types ──────────────────────────────────────────────────────────
    LAYOUT_SINGLE_COLUMN = "single_column"
    LAYOUT_TWO_COLUMN    = "two_column"
    LAYOUT_MIXED         = "mixed"
    LAYOUT_SIDEBAR       = "sidebar"

    # ─── Zone Types ────────────────────────────────────────────────────────────
    ZONE_HEADER  = "header_zone"    # Top of page (name, contact)
    ZONE_BODY    = "body_zone"      # Main content area
    ZONE_SIDEBAR = "sidebar_zone"   # Narrow side column
    ZONE_FOOTER  = "footer_zone"    # Bottom of page

    def __init__(self):
        # Column boundary thresholds (relative to page width)
        self.left_col_max  = 0.48
        self.right_col_min = 0.52
        self.sidebar_max   = 0.35   # Sidebar is narrower than 35% of page

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def analyze(
        self,
        text_blocks: list[dict],
        page_width:  float,
        page_height: float,
    ) -> dict:
        """
        Analyze layout of all text blocks on a page.

        Args:
            text_blocks:  List of block dicts from parser
                          Each block must have: text, bbox, page_num
            page_width:   Page width in points
            page_height:  Page height in points

        Returns:
            {
                "layout_type":     str,
                "zones":           dict[zone_name → list[block]],
                "columns":         dict[col_name  → list[block]],
                "ordered_blocks":  list[block],   # Final reading order
                "column_boundary": float,         # X position of column split
                "has_sidebar":     bool,
                "region_map":      list[dict],    # Block → region assignment
            }
        """
        if not text_blocks:
            return self._empty_result()

        logger.debug(
            f"Analyzing layout: {len(text_blocks)} blocks, "
            f"page {page_width:.0f}×{page_height:.0f}"
        )

        # ── Step 1: Detect layout type ────────────────────────────────────────
        layout_type, column_boundary = self._detect_layout_type(
            text_blocks, page_width
        )

        # ── Step 2: Assign blocks to columns ──────────────────────────────────
        columns = self._assign_columns(
            text_blocks, page_width, column_boundary
        )

        # ── Step 3: Assign blocks to zones ────────────────────────────────────
        zones = self._assign_zones(
            text_blocks, page_width, page_height
        )

        # ── Step 4: Detect sidebar ────────────────────────────────────────────
        has_sidebar = self._detect_sidebar(text_blocks, page_width)

        # ── Step 5: Build final reading order ─────────────────────────────────
        ordered_blocks = self._build_reading_order(
            text_blocks, layout_type, column_boundary, page_width
        )

        # ── Step 6: Build region map ──────────────────────────────────────────
        region_map = self._build_region_map(
            text_blocks, zones, columns
        )

        result = {
            "layout_type":     layout_type,
            "zones":           zones,
            "columns":         columns,
            "ordered_blocks":  ordered_blocks,
            "column_boundary": column_boundary,
            "has_sidebar":     has_sidebar,
            "region_map":      region_map,
        }

        logger.info(
            f"Layout analysis: type={layout_type}, "
            f"sidebar={has_sidebar}, "
            f"blocks={len(ordered_blocks)}"
        )
        return result

    # ─── Layout Type Detection ─────────────────────────────────────────────────
    def _detect_layout_type(
        self,
        blocks: list[dict],
        page_width: float,
    ) -> tuple[str, float]:
        """
        Determine if the layout is single-column, two-column,
        mixed, or sidebar-based.

        Returns:
            (layout_type, column_boundary_x)
        """
        if not blocks or page_width == 0:
            return self.LAYOUT_SINGLE_COLUMN, page_width / 2

        # Collect X start positions of all blocks
        x_starts = [
            b["bbox"]["x0"]
            for b in blocks
            if b.get("bbox") and b["bbox"].get("x0") is not None
        ]

        if not x_starts:
            return self.LAYOUT_SINGLE_COLUMN, page_width / 2

        # Normalize X positions to 0–1 range
        x_norm = [x / page_width for x in x_starts]

        # Count blocks in left vs right half
        left_count  = sum(1 for x in x_norm if x < 0.45)
        right_count = sum(1 for x in x_norm if x > 0.55)
        total       = len(x_norm)

        left_ratio  = left_count  / total if total else 0
        right_ratio = right_count / total if total else 0

        # Find natural column boundary using gap analysis
        column_boundary = self._find_column_gap(x_starts, page_width)

        # Classify layout
        if right_ratio > 0.20 and left_ratio > 0.20:
            # Check if it's a narrow sidebar or true two-column
            if self._has_narrow_sidebar(x_starts, page_width):
                return self.LAYOUT_SIDEBAR, column_boundary
            return self.LAYOUT_TWO_COLUMN, column_boundary

        return self.LAYOUT_SINGLE_COLUMN, page_width / 2

    def _find_column_gap(
        self,
        x_starts: list[float],
        page_width: float,
    ) -> float:
        """
        Find the natural gap between columns by looking for
        a sparse region in the X-position histogram.
        """
        if not x_starts:
            return page_width / 2

        # Build histogram of X positions (20 bins)
        hist, bin_edges = np.histogram(x_starts, bins=20, range=(0, page_width))

        # Look for the deepest gap in the middle 60% of the page
        mid_start = int(len(hist) * 0.20)
        mid_end   = int(len(hist) * 0.80)
        mid_hist  = hist[mid_start:mid_end]

        if len(mid_hist) == 0:
            return page_width / 2

        # Find bin with minimum count (the gap)
        min_bin = mid_start + int(np.argmin(mid_hist))
        gap_x   = (bin_edges[min_bin] + bin_edges[min_bin + 1]) / 2

        return float(gap_x)

    def _has_narrow_sidebar(
        self,
        x_starts: list[float],
        page_width: float,
    ) -> bool:
        """
        Check if the right-side content is a narrow sidebar
        (occupies less than 35% of page width).
        """
        right_starts = [x for x in x_starts if x / page_width > 0.55]
        if not right_starts:
            return False

        right_min = min(right_starts)
        sidebar_width = page_width - right_min
        return (sidebar_width / page_width) < self.sidebar_max

    # ─── Column Assignment ─────────────────────────────────────────────────────
    def _assign_columns(
        self,
        blocks: list[dict],
        page_width: float,
        column_boundary: float,
    ) -> dict[str, list[dict]]:
        """
        Assign each block to left, right, or full column.
        """
        columns = {"left": [], "right": [], "full": []}

        for block in blocks:
            bbox = block.get("bbox", {})
            x0   = bbox.get("x0", 0)
            x1   = bbox.get("x1", page_width)

            # Block spans most of the page width → full column
            block_width = x1 - x0
            if block_width > page_width * 0.70:
                columns["full"].append(block)
            elif x0 < column_boundary * 0.9:
                columns["left"].append(block)
            else:
                columns["right"].append(block)

        return columns

    # ─── Zone Assignment ───────────────────────────────────────────────────────
    def _assign_zones(
        self,
        blocks: list[dict],
        page_width: float,
        page_height: float,
    ) -> dict[str, list[dict]]:
        """
        Assign blocks to vertical zones:
          - Header zone: top 20% of page
          - Footer zone: bottom 10% of page
          - Body zone:   remaining area
        """
        zones = {
            self.ZONE_HEADER:  [],
            self.ZONE_BODY:    [],
            self.ZONE_FOOTER:  [],
            self.ZONE_SIDEBAR: [],
        }

        header_threshold = page_height * 0.20
        footer_threshold = page_height * 0.90

        for block in blocks:
            bbox = block.get("bbox", {})
            y0   = bbox.get("y0", 0)
            x0   = bbox.get("x0", 0)

            # Sidebar detection (very left or very right, narrow strip)
            if (x0 / page_width) > 0.70 or (x0 / page_width) < 0.05:
                if (bbox.get("x1", 0) - x0) < page_width * 0.30:
                    zones[self.ZONE_SIDEBAR].append(block)
                    continue

            if y0 < header_threshold:
                zones[self.ZONE_HEADER].append(block)
            elif y0 > footer_threshold:
                zones[self.ZONE_FOOTER].append(block)
            else:
                zones[self.ZONE_BODY].append(block)

        return zones

    # ─── Sidebar Detection ─────────────────────────────────────────────────────
    def _detect_sidebar(
        self,
        blocks: list[dict],
        page_width: float,
    ) -> bool:
        """
        Detect if the page has a sidebar layout.
        A sidebar is a narrow column (< 35% width) on left or right.
        """
        if not blocks or page_width == 0:
            return False

        x_starts = [b["bbox"]["x0"] for b in blocks if b.get("bbox")]
        if not x_starts:
            return False

        # Check for right sidebar
        right_blocks = [x for x in x_starts if x / page_width > 0.65]
        if len(right_blocks) / len(x_starts) > 0.15:
            return True

        # Check for left sidebar (blocks starting very close to left edge)
        # with main content starting further right
        left_edge_blocks  = [x for x in x_starts if x < page_width * 0.05]
        mid_start_blocks  = [x for x in x_starts if x > page_width * 0.35]
        if left_edge_blocks and mid_start_blocks:
            if len(left_edge_blocks) / len(x_starts) > 0.10:
                return True

        return False

    # ─── Reading Order ─────────────────────────────────────────────────────────
    def _build_reading_order(
        self,
        blocks: list[dict],
        layout_type: str,
        column_boundary: float,
        page_width: float,
    ) -> list[dict]:
        """
        Build the correct reading order for blocks based on layout type.

        Single column: simple top-to-bottom
        Two column:    left column top-to-bottom, then right column
        Sidebar:       main content first, sidebar second
        Mixed:         adaptive per-row grouping
        """
        if layout_type == self.LAYOUT_SINGLE_COLUMN:
            return self._order_single_column(blocks)

        elif layout_type == self.LAYOUT_TWO_COLUMN:
            return self._order_two_column(blocks, column_boundary)

        elif layout_type == self.LAYOUT_SIDEBAR:
            return self._order_sidebar(blocks, column_boundary, page_width)

        else:  # MIXED
            return self._order_mixed(blocks, column_boundary)

    def _order_single_column(self, blocks: list[dict]) -> list[dict]:
        """Sort blocks top-to-bottom for single column layout."""
        return sorted(
            blocks,
            key=lambda b: (b["bbox"].get("y0", 0), b["bbox"].get("x0", 0))
        )

    def _order_two_column(
        self,
        blocks: list[dict],
        column_boundary: float,
    ) -> list[dict]:
        """
        Order blocks for two-column layout:
        Read entire left column first, then entire right column.
        Within each column, sort top-to-bottom.
        """
        left_blocks  = []
        right_blocks = []
        full_blocks  = []

        for block in blocks:
            x0 = block["bbox"].get("x0", 0)
            x1 = block["bbox"].get("x1", 0)

            # Full-width blocks interrupt column flow
            if (x1 - x0) > column_boundary * 0.8:
                full_blocks.append(block)
            elif x0 < column_boundary:
                left_blocks.append(block)
            else:
                right_blocks.append(block)

        # Sort each group by Y position
        left_blocks.sort( key=lambda b: b["bbox"].get("y0", 0))
        right_blocks.sort(key=lambda b: b["bbox"].get("y0", 0))
        full_blocks.sort( key=lambda b: b["bbox"].get("y0", 0))

        # Interleave full-width blocks at correct vertical positions
        return self._interleave_full_blocks(
            left_blocks, right_blocks, full_blocks
        )

    def _order_sidebar(
        self,
        blocks: list[dict],
        column_boundary: float,
        page_width: float,
    ) -> list[dict]:
        """
        Order blocks for sidebar layout.
        Main content first (larger column), sidebar second.
        """
        main_blocks    = []
        sidebar_blocks = []

        for block in blocks:
            x0 = block["bbox"].get("x0", 0)
            # Determine which is the sidebar (narrower column)
            if column_boundary < page_width * 0.40:
                # Left sidebar
                if x0 < column_boundary:
                    sidebar_blocks.append(block)
                else:
                    main_blocks.append(block)
            else:
                # Right sidebar
                if x0 >= column_boundary:
                    sidebar_blocks.append(block)
                else:
                    main_blocks.append(block)

        main_blocks.sort(   key=lambda b: b["bbox"].get("y0", 0))
        sidebar_blocks.sort(key=lambda b: b["bbox"].get("y0", 0))

        return main_blocks + sidebar_blocks

    def _order_mixed(
        self,
        blocks: list[dict],
        column_boundary: float,
    ) -> list[dict]:
        """
        Adaptive ordering for mixed layouts.
        Groups blocks into horizontal rows, then handles each row.
        """
        if not blocks:
            return []

        # Group blocks into horizontal rows (within 20px Y tolerance)
        row_tolerance = 20
        rows = []
        used = set()

        sorted_by_y = sorted(blocks, key=lambda b: b["bbox"].get("y0", 0))

        for i, block in enumerate(sorted_by_y):
            if i in used:
                continue
            y0  = block["bbox"].get("y0", 0)
            row = [block]
            used.add(i)

            for j, other in enumerate(sorted_by_y):
                if j in used:
                    continue
                other_y0 = other["bbox"].get("y0", 0)
                if abs(other_y0 - y0) <= row_tolerance:
                    row.append(other)
                    used.add(j)

            # Sort row left-to-right
            row.sort(key=lambda b: b["bbox"].get("x0", 0))
            rows.append(row)

        # Flatten rows
        return [block for row in rows for block in row]

    def _interleave_full_blocks(
        self,
        left: list[dict],
        right: list[dict],
        full: list[dict],
    ) -> list[dict]:
        """
        Interleave full-width blocks between column blocks
        at their correct vertical positions.
        """
        if not full:
            return left + right

        result = []
        left_idx = right_idx = full_idx = 0

        # Process all blocks in Y order
        all_blocks = (
            [(b, "left")  for b in left] +
            [(b, "right") for b in right] +
            [(b, "full")  for b in full]
        )
        all_blocks.sort(key=lambda x: x[0]["bbox"].get("y0", 0))

        return [b for b, _ in all_blocks]

    # ─── Region Map ────────────────────────────────────────────────────────────
    def _build_region_map(
        self,
        blocks: list[dict],
        zones: dict,
        columns: dict,
    ) -> list[dict]:
        """
        Build a map assigning each block its zone and column.
        """
        # Create reverse lookup: block id → zone
        zone_lookup   = {}
        column_lookup = {}

        for zone_name, zone_blocks in zones.items():
            for block in zone_blocks:
                bid = id(block)
                zone_lookup[bid] = zone_name

        for col_name, col_blocks in columns.items():
            for block in col_blocks:
                bid = id(block)
                column_lookup[bid] = col_name

        region_map = []
        for block in blocks:
            bid = id(block)
            region_map.append({
                "text":   block.get("text", "")[:50],
                "zone":   zone_lookup.get(bid,   "body_zone"),
                "column": column_lookup.get(bid, "full"),
            })

        return region_map

    # ─── Utilities ─────────────────────────────────────────────────────────────
    def _empty_result(self) -> dict:
        return {
            "layout_type":     self.LAYOUT_SINGLE_COLUMN,
            "zones":           {z: [] for z in [
                self.ZONE_HEADER, self.ZONE_BODY,
                self.ZONE_FOOTER, self.ZONE_SIDEBAR
            ]},
            "columns":         {"left": [], "right": [], "full": []},
            "ordered_blocks":  [],
            "column_boundary": 0.0,
            "has_sidebar":     False,
            "region_map":      [],
        }

    def get_text_in_reading_order(
        self,
        text_blocks: list[dict],
        page_width: float,
        page_height: float,
    ) -> str:
        """
        Convenience method: analyze layout and return
        full text in correct reading order.
        """
        result = self.analyze(text_blocks, page_width, page_height)
        ordered = result["ordered_blocks"]
        return "\n".join(
            b["text"] for b in ordered if b.get("text", "").strip()
        )


# ─── Singleton ─────────────────────────────────────────────────────────────────
layout_analyzer = LayoutAnalyzer()
