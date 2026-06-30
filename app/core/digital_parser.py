# app/core/digital_parser.py

from pathlib import Path
from typing import Optional

import fitz          # PyMuPDF
import pdfplumber

from app.utils.logger import get_logger
from app.utils.helpers import normalize_whitespace
from app.utils import regex_patterns as patterns

logger = get_logger(__name__)


class DigitalPDFParser:
    """
    Extracts text and layout data from digital (text-layer) PDFs.

    Strategy:
      1. PyMuPDF  → fast extraction with font metadata + bounding boxes
      2. pdfplumber → fallback for complex layouts and table extraction
    """

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def parse(self, file_path: str | Path) -> dict:
        """
        Parse a digital PDF and return structured text with metadata.

        Returns:
            {
                "full_text":    str,
                "pages":        list[PageData],
                "text_blocks":  list[TextBlock],
                "tables":       list[TableData],
                "metadata":     dict,
            }
        """
        file_path = Path(file_path)
        logger.info(f"Parsing digital PDF: {file_path.name}")

        # Primary extraction via PyMuPDF
        pymupdf_result = self._parse_with_pymupdf(file_path)

        # Extract tables via pdfplumber
        tables = self._extract_tables_with_pdfplumber(file_path)

        # Combine results
        full_text = self._build_full_text(pymupdf_result["pages"])
        pymupdf_result["full_text"] = full_text
        pymupdf_result["tables"]    = tables

        logger.info(
            f"Digital parse complete: {len(full_text)} chars, "
            f"{len(pymupdf_result['pages'])} pages, "
            f"{len(tables)} tables"
        )
        return pymupdf_result

    # ─── PyMuPDF Extraction ────────────────────────────────────────────────────
    def _parse_with_pymupdf(self, file_path: Path) -> dict:
        """
        Extract text blocks with full positional and font metadata.
        """
        doc = fitz.open(str(file_path))
        pages      = []
        all_blocks = []

        try:
            metadata = doc.metadata or {}

            for page_num in range(len(doc)):
                page        = doc[page_num]
                page_width  = page.rect.width
                page_height = page.rect.height
                page_data   = self._extract_page_data(
                    page, page_num + 1, page_width, page_height
                )
                pages.append(page_data)
                all_blocks.extend(page_data["blocks"])

            return {
                "pages":       pages,
                "text_blocks": all_blocks,
                "metadata": {
                    "title":    metadata.get("title",    ""),
                    "author":   metadata.get("author",   ""),
                    "creator":  metadata.get("creator",  ""),
                    "page_count": len(doc),
                },
            }
        finally:
            doc.close()

    def _extract_page_data(
        self,
        page: fitz.Page,
        page_num: int,
        page_width: float,
        page_height: float,
    ) -> dict:
        """
        Extract all text blocks from a single page with full metadata.
        """
        raw_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks   = []
        page_text_parts = []

        for block in raw_dict.get("blocks", []):
            if block.get("type") != 0:  # Skip non-text blocks
                continue

            block_text  = ""
            block_spans = []
            max_font_size = 0.0
            is_bold     = False
            font_name   = ""

            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if not span_text:
                        continue

                    span_font_size = span.get("size", 0.0)
                    span_font_name = span.get("font", "")
                    span_is_bold   = (
                        "bold" in span_font_name.lower()
                        or span.get("flags", 0) & 2**4  # Bold flag
                    )

                    if span_font_size > max_font_size:
                        max_font_size = span_font_size
                        font_name     = span_font_name
                    if span_is_bold:
                        is_bold = True

                    line_text += span_text + " "
                    block_spans.append({
                        "text":      span_text,
                        "font_size": round(span_font_size, 1),
                        "font_name": span_font_name,
                        "is_bold":   span_is_bold,
                        "color":     span.get("color", 0),
                        "bbox":      span.get("bbox", []),
                    })

                block_text += line_text.strip() + "\n"

            block_text = block_text.strip()
            if not block_text:
                continue

            # Bounding box
            bbox = block.get("bbox", [0, 0, 0, 0])
            x0, y0, x1, y1 = bbox

            # Determine column position
            column = self._get_column(x0, page_width)

            block_entry = {
                "text":        block_text,
                "page_num":    page_num,
                "bbox":        {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
                "font_size":   round(max_font_size, 1),
                "font_name":   font_name,
                "is_bold":     is_bold,
                "column":      column,
                "spans":       block_spans,
                "is_header":   self._is_header_block(block_text, max_font_size, is_bold),
            }

            blocks.append(block_entry)
            page_text_parts.append(block_text)

        # Sort blocks by reading order (top-to-bottom, left-to-right per column)
        blocks = self._sort_blocks_by_reading_order(blocks)

        return {
            "page_num":    page_num,
            "width":       page_width,
            "height":      page_height,
            "blocks":      blocks,
            "page_text":   "\n".join(page_text_parts),
        }

    # ─── pdfplumber Table Extraction ───────────────────────────────────────────
    def _extract_tables_with_pdfplumber(self, file_path: Path) -> list[dict]:
        """
        Use pdfplumber to extract structured tables from the PDF.
        Returns list of table dicts with headers and rows.
        """
        tables = []
        try:
            with pdfplumber.open(str(file_path)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    raw_tables = page.extract_tables()
                    for table_idx, table in enumerate(raw_tables):
                        if not table or len(table) < 2:
                            continue

                        # First row as headers
                        headers = [
                            str(cell).strip() if cell else f"col_{i}"
                            for i, cell in enumerate(table[0])
                        ]
                        rows = []
                        for row in table[1:]:
                            row_dict = {
                                headers[i]: str(cell).strip() if cell else ""
                                for i, cell in enumerate(row)
                                if i < len(headers)
                            }
                            rows.append(row_dict)

                        tables.append({
                            "page_num":  page_num,
                            "table_idx": table_idx,
                            "headers":   headers,
                            "rows":      rows,
                            "row_count": len(rows),
                        })

        except Exception as e:
            logger.warning(f"pdfplumber table extraction failed: {e}")

        return tables

    # ─── Utilities ─────────────────────────────────────────────────────────────
    def _build_full_text(self, pages: list[dict]) -> str:
        """Concatenate all page texts into a single clean string."""
        parts = []
        for page in pages:
            page_text = " ".join(
                block["text"] for block in page["blocks"]
            )
            parts.append(page_text)
        return normalize_whitespace("\n\n".join(parts))

    def _get_column(self, x0: float, page_width: float) -> str:
        """
        Determine which column a block belongs to.
        Returns 'left', 'right', or 'full'.
        """
        if page_width == 0:
            return "full"
        relative_x = x0 / page_width
        if relative_x < 0.45:
            return "left"
        elif relative_x > 0.55:
            return "right"
        return "full"

    def _is_header_block(
        self,
        text: str,
        font_size: float,
        is_bold: bool,
    ) -> bool:
        """Heuristic to determine if a block is a section header."""
        text = text.strip()
        if not text or len(text) > 80:
            return False
        if font_size >= 13.0 or is_bold:
            return True
        if text.isupper() and 2 < len(text) < 50:
            return True
        if patterns.ALL_CAPS_HEADER.match(text):
            return True
        return False

    def _sort_blocks_by_reading_order(self, blocks: list[dict]) -> list[dict]:
        """
        Sort blocks by reading order:
        - Primary: Y position (top to bottom)
        - Secondary: Column (left before right)
        - Tertiary: X position (left to right)
        """
        def sort_key(b):
            y0     = b["bbox"]["y0"]
            x0     = b["bbox"]["x0"]
            column = 0 if b["column"] in ("left", "full") else 1
            return (round(y0 / 15), column, x0)  # Group rows within 15px

        return sorted(blocks, key=sort_key)

    def extract_text_only(self, file_path: str | Path) -> str:
        """
        Quick extraction — returns plain text only, no metadata.
        Useful for fast pre-processing checks.
        """
        file_path = Path(file_path)
        doc = fitz.open(str(file_path))
        try:
            parts = []
            for page in doc:
                parts.append(page.get_text("text"))
            return normalize_whitespace("\n\n".join(parts))
        finally:
            doc.close()

    def get_word_positions(self, file_path: str | Path) -> list[dict]:
        """
        Extract individual words with their bounding boxes.
        Used for fine-grained layout analysis.
        """
        file_path = Path(file_path)
        doc = fitz.open(str(file_path))
        words = []
        try:
            for page_num, page in enumerate(doc, start=1):
                for word in page.get_text("words"):
                    x0, y0, x1, y1, text, *_ = word
                    if text.strip():
                        words.append({
                            "text":     text.strip(),
                            "page_num": page_num,
                            "x0": x0, "y0": y0,
                            "x1": x1, "y1": y1,
                        })
        finally:
            doc.close()
        return words


# ─── Singleton ─────────────────────────────────────────────────────────────────
digital_parser = DigitalPDFParser()
