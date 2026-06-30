
# app/core/__init__.py

from app.core.pdf_detector   import pdf_detector,   PDFDetector
from app.core.digital_parser import digital_parser, DigitalPDFParser
from app.core.ocr_parser     import ocr_parser,     OCRParser

__all__ = [
    "pdf_detector",   "PDFDetector",
    "digital_parser", "DigitalPDFParser",
    "ocr_parser",     "OCRParser",
]
