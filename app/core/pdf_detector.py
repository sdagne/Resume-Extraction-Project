# app/core/pdf_detector.py

from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from app.utils.constants import PDFType
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ─── Thresholds ────────────────────────────────────────────────────────────────
MIN_TEXT_CHARS_PER_PAGE  = 50    # Below this → page is likely scanned
IMAGE_COVERAGE_THRESHOLD = 0.60  # If >60% of page is image → likely scanned


class PDFDetector:
    """
    Analyzes a PDF file to determine whether it is:
      - DIGITAL  : Selectable text layer present
      - SCANNED  : Image-based, requires OCR
      - MIXED    : Some pages are digital, some are scanned

    Also extracts basic metadata: page count, presence of
    tables/images, multi-column layout detection.
    """

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def detect(self, file_path: str | Path) -> dict:
        """
        Analyze a PDF and return its type and metadata.

        Returns:
            {
                "pdf_type":       "digital" | "scanned" | "mixed",
                "page_count":     int,
                "has_images":     bool,
                "has_tables":     bool,
                "is_multicolumn": bool,
                "digital_pages":  list[int],
                "scanned_pages":  list[int],
                "avg_text_per_page": float,
            }
        """
        file_path = Path(file_path)
        logger.info(f"Detecting PDF type for: {file_path.name}")

        try:
            doc = fitz.open(str(file_path))
        except Exception as e:
            logger.error(f"Failed to open PDF: {e}")
            raise ValueError(f"Cannot open PDF file: {file_path}") from e

        try:
            page_count    = len(doc)
            digital_pages = []
            scanned_pages = []
            has_images    = False
            has_tables    = False
            total_text    = 0

            for page_num in range(page_count):
                page = doc[page_num]

                # ── Text analysis ──────────────────────────────────────────────
                text = page.get_text("text").strip()
                char_count = len(text)
                total_text += char_count

                # ── Image analysis ────────────────────────────────────────────
                images = page.get_images(full=True)
                if images:
                    has_images = True

                # ── Determine if page is scanned ──────────────────────────────
                if char_count < MIN_TEXT_CHARS_PER_PAGE:
                    if self._is_image_dominant(page):
                        scanned_pages.append(page_num + 1)
                    else:
                        # Very little text but not image-dominant → still digital
                        digital_pages.append(page_num + 1)
                else:
                    digital_pages.append(page_num + 1)

                # ── Table detection (heuristic) ───────────────────────────────
                if not has_tables:
                    has_tables = self._detect_table_presence(page)

            # ── Multi-column detection ────────────────────────────────────────
            is_multicolumn = self._detect_multicolumn(doc)

            # ── Determine overall PDF type ────────────────────────────────────
            pdf_type = self._classify_pdf_type(
                digital_pages, scanned_pages, page_count
            )

            avg_text = total_text / page_count if page_count else 0

            result = {
                "pdf_type":          pdf_type,
                "page_count":        page_count,
                "has_images":        has_images,
                "has_tables":        has_tables,
                "is_multicolumn":    is_multicolumn,
                "digital_pages":     digital_pages,
                "scanned_pages":     scanned_pages,
                "avg_text_per_page": round(avg_text, 1),
            }

            logger.info(
                f"PDF detected → type={pdf_type}, pages={page_count}, "
                f"digital={len(digital_pages)}, scanned={len(scanned_pages)}, "
                f"multicolumn={is_multicolumn}"
            )
            return result

        finally:
            doc.close()

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _is_image_dominant(self, page: fitz.Page) -> bool:
        """
        Check if a page is dominated by images (suggesting it's scanned).
        Compares total image area to page area.
        """
        page_area = page.rect.width * page.rect.height
        if page_area == 0:
            return False

        total_image_area = 0.0
        for img in page.get_images(full=True):
            try:
                xref = img[0]
                # Get image bounding box on the page
                rects = page.get_image_rects(xref)
                for rect in rects:
                    total_image_area += rect.width * rect.height
            except Exception:
                pass

        coverage = total_image_area / page_area
        return coverage >= IMAGE_COVERAGE_THRESHOLD

    def _detect_table_presence(self, page: fitz.Page) -> bool:
        """
        Heuristic table detection using line drawing analysis.
        Tables typically have many horizontal/vertical lines.
        """
        try:
            drawings = page.get_drawings()
            line_count = sum(
                1 for d in drawings
                if d.get("type") in ("l", "re")  # lines and rectangles
            )
            return line_count >= 10
        except Exception:
            return False

    def _detect_multicolumn(self, doc: fitz.Document) -> bool:
        """
        Detect multi-column layout by analyzing text block X-positions.
        If text blocks cluster into 2+ distinct X-ranges → multi-column.
        """
        try:
            # Sample first 2 pages for speed
            sample_pages = min(2, len(doc))
            x_positions = []

            for page_num in range(sample_pages):
                page = doc[page_num]
                blocks = page.get_text("dict").get("blocks", [])
                for block in blocks:
                    if block.get("type") == 0:  # Text block
                        x0 = block["bbox"][0]
                        x_positions.append(x0)

            if not x_positions:
                return False

            page_width = doc[0].rect.width
            mid = page_width / 2

            # Count blocks in left vs right half
            left_blocks  = sum(1 for x in x_positions if x < mid * 0.4)
            right_blocks = sum(1 for x in x_positions if x > mid * 0.6)

            total = len(x_positions)
            if total == 0:
                return False

            # If both halves have significant content → multi-column
            left_ratio  = left_blocks  / total
            right_ratio = right_blocks / total

            is_multi = left_ratio > 0.15 and right_ratio > 0.15
            logger.debug(
                f"Multi-column check: left={left_ratio:.2f}, "
                f"right={right_ratio:.2f}, result={is_multi}"
            )
            return is_multi

        except Exception as e:
            logger.warning(f"Multi-column detection failed: {e}")
            return False

    def _classify_pdf_type(
        self,
        digital_pages: list[int],
        scanned_pages: list[int],
        total_pages: int,
    ) -> str:
        """Classify overall PDF type based on per-page analysis."""
        if total_pages == 0:
            return PDFType.DIGITAL

        scanned_ratio = len(scanned_pages) / total_pages

        if scanned_ratio == 0:
            return PDFType.DIGITAL
        elif scanned_ratio == 1.0:
            return PDFType.SCANNED
        else:
            return PDFType.MIXED

    def get_page_images(
        self,
        file_path: str | Path,
        page_numbers: Optional[list[int]] = None,
        dpi: int = 200,
    ) -> list[dict]:
        """
        Render PDF pages as images (for OCR processing).

        Args:
            file_path:    Path to PDF file
            page_numbers: 1-based page numbers to render (None = all)
            dpi:          Resolution for rendering

        Returns:
            List of {"page_num": int, "image_bytes": bytes, "width": int, "height": int}
        """
        file_path = Path(file_path)
        doc = fitz.open(str(file_path))
        results = []

        try:
            pages_to_render = (
                [p - 1 for p in page_numbers]  # Convert to 0-based
                if page_numbers
                else range(len(doc))
            )

            zoom = dpi / 72  # 72 DPI is PyMuPDF default
            matrix = fitz.Matrix(zoom, zoom)

            for page_num in pages_to_render:
                if page_num < 0 or page_num >= len(doc):
                    continue

                page = doc[page_num]
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)

                results.append({
                    "page_num":    page_num + 1,
                    "image_bytes": pixmap.tobytes("png"),
                    "width":       pixmap.width,
                    "height":      pixmap.height,
                })

            logger.debug(f"Rendered {len(results)} pages as images")
            return results

        finally:
            doc.close()


# ─── Singleton ─────────────────────────────────────────────────────────────────
pdf_detector = PDFDetector()
