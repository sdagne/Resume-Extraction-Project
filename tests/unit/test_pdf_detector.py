import pytest
from app.core.pdf_detector import is_scanned_pdf
import os

def test_is_scanned_pdf_not_found():
    with pytest.raises(Exception):
        is_scanned_pdf("non_existent.pdf")

# Add more mock tests or sample PDF tests

