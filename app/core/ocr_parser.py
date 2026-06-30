# app/core/ocr_parser.py

import io
import numpy as np
from pathlib import Path
from typing import Optional

import cv2
from PIL import Image
try:
    from paddleocr import PaddleOCR, PPStructure
except ImportError:
    from paddleocr import PaddleOCR
    PPStructure = None
    import logging
    logging.getLogger("uvicorn").warning("PPStructure not found in paddleocr. Layout analysis will be limited.")

from app.config import settings
from app.utils.logger import get_logger
from app.utils.helpers import normalize_whitespace

logger = get_logger(__name__)


class OCRParser:
    """
    Extracts text from scanned PDF pages using PaddleOCR.

    Pipeline:
      1. Render PDF pages to images (via pdf_detector)
      2. Preprocess images (deskew, denoise, contrast)
      3. Run PaddleOCR for text + bounding boxes
      4. Run PP-Structure for layout region detection
      5. Reconstruct logical reading order
    """

    def __init__(self):
        self._ocr_engine       = None
        self._structure_engine = None

    # ─── Lazy Initialization ───────────────────────────────────────────────────
    @property
    def ocr_engine(self) -> PaddleOCR:
        """Lazy-load PaddleOCR engine (heavy initialization)."""
        if self._ocr_engine is None:
            logger.info("Initializing PaddleOCR engine...")
            self._ocr_engine = PaddleOCR(
                use_angle_cls=True,
                lang=settings.OCR_LANGUAGE,
                use_gpu=settings.OCR_USE_GPU,
                show_log=False,
                enable_mkldnn=True,      # CPU optimization
            )
            logger.info("PaddleOCR engine ready")
        return self._ocr_engine

    @property
    def structure_engine(self) -> PPStructure:
        """Lazy-load PP-Structure engine for layout analysis."""
        if self._structure_engine is None:
            logger.info("Initializing PP-Structure engine...")
            self._structure_engine = PPStructure(
                show_log=False,
                use_gpu=settings.OCR_USE_GPU,
                table=True,
                ocr=True,
                lang=settings.OCR_LANGUAGE,
            )
            logger.info("PP-Structure engine ready")
        return self._structure_engine

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def parse(
        self,
        file_path: str | Path,
        page_images: Optional[list[dict]] = None,
    ) -> dict:
        """
        OCR-parse a scanned PDF.

        Args:
            file_path:   Path to the PDF file
            page_images: Pre-rendered page images from PDFDetector
                         (if None, will render internally)

        Returns:
            {
                "full_text":   str,
                "pages":       list[PageOCRData],
                "text_blocks": list[OCRBlock],
                "tables":      list[TableData],
            }
        """
        file_path = Path(file_path)
        logger.info(f"OCR parsing: {file_path.name}")

        # Render pages to images if not provided
        if page_images is None:
            from app.core.pdf_detector import pdf_detector
            page_images = pdf_detector.get_page_images(file_path, dpi=200)

        pages      = []
        all_blocks = []
        all_tables = []

        for page_data in page_images:
            page_num    = page_data["page_num"]
            image_bytes = page_data["image_bytes"]

            logger.debug(f"OCR processing page {page_num}")

            # Preprocess image
            processed_img = self._preprocess_image(image_bytes)

            # Run PP-Structure for layout-aware extraction
            layout_result = self._run_pp_structure(processed_img)

            # Parse layout regions
            page_result = self._parse_layout_regions(
                layout_result, page_num, page_data["width"], page_data["height"]
            )

            pages.append(page_result)
            all_blocks.extend(page_result["blocks"])
            all_tables.extend(page_result.get("tables", []))

        # Build full text
        full_text = self._build_full_text(pages)

        logger.info(
            f"OCR complete: {len(full_text)} chars, "
            f"{len(pages)} pages, {len(all_tables)} tables"
        )

        return {
            "full_text":   full_text,
            "pages":       pages,
            "text_blocks": all_blocks,
            "tables":      all_tables,
        }

    # ─── Image Preprocessing ───────────────────────────────────────────────────
    def _preprocess_image(self, image_bytes: bytes) -> np.ndarray:
        """
        Apply image preprocessing to improve OCR accuracy:
          - Convert to grayscale
          - Deskew (straighten rotated scans)
          - Denoise
          - Enhance contrast (CLAHE)
          - Binarize (Otsu thresholding)
        """
        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError("Failed to decode image bytes")

        # ── Grayscale ─────────────────────────────────────────────────────────
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # ── Deskew ────────────────────────────────────────────────────────────
        gray = self._deskew(gray)

        # ── Denoise ───────────────────────────────────────────────────────────
        denoised = cv2.fastNlMeansDenoising(gray, h=10)

        # ── CLAHE Contrast Enhancement ────────────────────────────────────────
        clahe     = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced  = clahe.apply(denoised)

        # ── Binarization (Otsu) ───────────────────────────────────────────────
        _, binary = cv2.threshold(
            enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        # Convert back to BGR for PaddleOCR (expects 3-channel)
        result = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        return result

    def _deskew(self, gray: np.ndarray) -> np.ndarray:
        """
        Detect and correct skew angle in a grayscale image.
        Uses Hough line detection to find the dominant angle.
        """
        try:
            # Edge detection
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)

            # Hough transform
            lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)

            if lines is None:
                return gray

            # Calculate dominant angle
            angles = []
            for rho, theta in lines[:, 0]:
                angle = (theta * 180 / np.pi) - 90
                if abs(angle) < 45:  # Ignore near-vertical lines
                    angles.append(angle)

            if not angles:
                return gray

            median_angle = np.median(angles)

            # Only deskew if angle is significant
            if abs(median_angle) < 0.5:
                return gray

            logger.debug(f"Deskewing by {median_angle:.2f} degrees")

            # Rotate image
            h, w   = gray.shape
            center = (w // 2, h // 2)
            M      = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            rotated = cv2.warpAffine(
                gray, M, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            return rotated

        except Exception as e:
            logger.warning(f"Deskew failed, using original: {e}")
            return gray

    # ─── PP-Structure ──────────────────────────────────────────────────────────
    def _run_pp_structure(self, img: np.ndarray) -> list[dict]:
        """
        Run PP-Structure layout analysis on a preprocessed image.
        Returns list of detected regions with type and content.
        """
        try:
            result = self.structure_engine(img)
            return result if result else []
        except Exception as e:
            logger.warning(f"PP-Structure failed, falling back to plain OCR: {e}")
            return self._run_plain_ocr(img)

    def _run_plain_ocr(self, img: np.ndarray) -> list[dict]:
        """
        Fallback: run plain PaddleOCR without layout analysis.
        Returns results in PP-Structure-compatible format.
        """
        try:
            result = self.ocr_engine.ocr(img, cls=True)
            if not result or not result[0]:
                return []

            # Convert to PP-Structure format
            regions = []
            for line in result[0]:
                bbox, (text, confidence) = line
                if confidence >= settings.OCR_CONFIDENCE_THRESHOLD:
                    regions.append({
                        "type": "text",
                        "bbox": bbox,
                        "res":  [{"text": text, "confidence": confidence}],
                    })
            return regions

        except Exception as e:
            logger.error(f"Plain OCR also failed: {e}")
            return []

    # ─── Parse Layout Regions ──────────────────────────────────────────────────
    def _parse_layout_regions(
        self,
        layout_result: list[dict],
        page_num: int,
        page_width: float,
        page_height: float,
    ) -> dict:
        """
        Parse PP-Structure layout regions into structured blocks.
        Handles text, table, figure, and title region types.
        """
        blocks = []
        tables = []

        for region in layout_result:
            region_type = region.get("type", "text").lower()
            bbox        = region.get("bbox", [0, 0, 0, 0])
            res         = region.get("res",  [])

            if region_type == "table":
                # Extract table structure
                table_data = self._extract_table_from_region(res, page_num)
                if table_data:
                    tables.append(table_data)
                    # Also add table text as a block
                    table_text = self._table_to_text(table_data)
                    if table_text:
                        blocks.append(self._make_block(
                            table_text, page_num, bbox,
                            page_width, region_type="table"
                        ))

            elif region_type in ("text", "title", "list", "header"):
                # Extract text from region
                text = self._extract_text_from_region(res)
                if text:
                    is_header = region_type in ("title", "header")
                    blocks.append(self._make_block(
                        text, page_num, bbox, page_width,
                        region_type=region_type,
                        is_header=is_header,
                    ))

            elif region_type == "figure":
                # Skip figures (images within scanned docs)
                logger.debug(f"Skipping figure region on page {page_num}")

        # Sort blocks by reading order
        blocks = self._sort_blocks(blocks)

        return {
            "page_num": page_num,
            "width":    page_width,
            "height":   page_height,
            "blocks":   blocks,
            "tables":   tables,
            "page_text": "\n".join(b["text"] for b in blocks),
        }

    def _extract_text_from_region(self, res: list | dict) -> str:
        """Extract plain text from a PP-Structure region result."""
        if not res:
            return ""

        texts = []

        # res can be a list of OCR lines or a dict
        if isinstance(res, list):
            for item in res:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    conf = item.get("confidence", 1.0)
                    if text and conf >= settings.OCR_CONFIDENCE_THRESHOLD:
                        texts.append(text.strip())
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    # PaddleOCR format: [[bbox], [text, confidence]]
                    try:
                        text, conf = item[1]
                        if conf >= settings.OCR_CONFIDENCE_THRESHOLD:
                            texts.append(str(text).strip())
                    except (ValueError, TypeError):
                        pass

        elif isinstance(res, dict):
            text = res.get("text", "")
            if text:
                texts.append(text.strip())

        return normalize_whitespace(" ".join(texts))

    def _extract_table_from_region(
        self,
        res: list | dict,
        page_num: int,
    ) -> Optional[dict]:
        """Extract structured table data from a PP-Structure table region."""
        try:
            if isinstance(res, dict):
                # PP-Structure returns HTML for tables
                html = res.get("html", "")
                if html:
                    return self._parse_table_html(html, page_num)

            elif isinstance(res, list) and res:
                # Fallback: treat as text rows
                rows = []
                for item in res:
                    text = self._extract_text_from_region([item])
                    if text:
                        rows.append({"col_0": text})
                if rows:
                    return {
                        "page_num": page_num,
                        "headers":  ["col_0"],
                        "rows":     rows,
                    }
        except Exception as e:
            logger.warning(f"Table extraction from region failed: {e}")
        return None

    def _parse_table_html(self, html: str, page_num: int) -> Optional[dict]:
        """Parse HTML table string into structured dict."""
        try:
            from html.parser import HTMLParser

            class TableParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.rows = []
                    self._current_row = []
                    self._current_cell = ""
                    self._in_cell = False

                def handle_starttag(self, tag, attrs):
                    if tag in ("td", "th"):
                        self._in_cell = True
                        self._current_cell = ""
                    elif tag == "tr":
                        self._current_row = []

                def handle_endtag(self, tag):
                    if tag in ("td", "th"):
                        self._current_row.append(self._current_cell.strip())
                        self._in_cell = False
                    elif tag == "tr":
                        if self._current_row:
                            self.rows.append(self._current_row)

                def handle_data(self, data):
                    if self._in_cell:
                        self._current_cell += data

            parser = TableParser()
            parser.feed(html)

            if not parser.rows:
                return None

            headers = parser.rows[0] if parser.rows else []
            headers = [h or f"col_{i}" for i, h in enumerate(headers)]
            rows = []
            for row in parser.rows[1:]:
                row_dict = {
                    headers[i]: row[i] if i < len(row) else ""
                    for i in range(len(headers))
                }
                rows.append(row_dict)

            return {
                "page_num": page_num,
                "headers":  headers,
                "rows":     rows,
                "row_count":len(rows),
            }

        except Exception as e:
            logger.warning(f"HTML table parsing failed: {e}")
            return None

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _make_block(
        self,
        text: str,
        page_num: int,
        bbox: list,
        page_width: float,
        region_type: str = "text",
        is_header: bool = False,
    ) -> dict:
        """Create a standardized text block dict."""
        x0 = bbox[0] if len(bbox) >= 1 else 0
        y0 = bbox[1] if len(bbox) >= 2 else 0
        x1 = bbox[2] if len(bbox) >= 3 else 0
        y1 = bbox[3] if len(bbox) >= 4 else 0

        column = "left"
        if page_width > 0:
            relative_x = x0 / page_width
            if relative_x > 0.55:
                column = "right"
            elif relative_x < 0.45:
                column = "left"
            else:
                column = "full"

        return {
            "text":        text,
            "page_num":    page_num,
            "bbox":        {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
            "font_size":   0.0,       # Not available from OCR
            "font_name":   "",
            "is_bold":     is_header,
            "is_header":   is_header,
            "column":      column,
            "region_type": region_type,
        }

    def _table_to_text(self, table: dict) -> str:
        """Convert a table dict to readable plain text."""
        if not table or not table.get("rows"):
            return ""
        lines = [" | ".join(table.get("headers", []))]
        for row in table["rows"]:
            lines.append(" | ".join(str(v) for v in row.values()))
        return "\n".join(lines)

    def _sort_blocks(self, blocks: list[dict]) -> list[dict]:
        """Sort OCR blocks by reading order (Y then X)."""
        def sort_key(b):
            y0     = b["bbox"]["y0"]
            x0     = b["bbox"]["x0"]
            column = 0 if b["column"] in ("left", "full") else 1
            return (round(y0 / 20), column, x0)

        return sorted(blocks, key=sort_key)

    def _build_full_text(self, pages: list[dict]) -> str:
        """Build full document text from all pages."""
        parts = [page.get("page_text", "") for page in pages]
        return normalize_whitespace("\n\n".join(filter(None, parts)))

    def parse_image_file(self, image_path: str | Path) -> str:
        """
        OCR a standalone image file (PNG, JPG, etc.).
        Returns extracted plain text.
        """
        image_path = Path(image_path)
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")

        processed = self._preprocess_image(
            cv2.imencode(".png", img)[1].tobytes()
        )
        regions = self._run_pp_structure(processed)
        return self._extract_text_from_region(regions)


# ─── Singleton ─────────────────────────────────────────────────────────────────
ocr_parser = OCRParser()
