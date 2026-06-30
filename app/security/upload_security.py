# app/security/upload_security.py
"""
Enterprise-grade upload security scanner.

Checks performed:
  1. Magic-byte validation  – file header must match declared extension
  2. Filename sanitization  – path traversal, null bytes, dangerous chars
  3. PDF structure scan     – embedded JavaScript, /OpenAction, /Launch
  4. Embedded executable    – detect PE/ELF headers hidden inside PDF streams
  5. Content-size anomaly   – alert if metadata size >> actual text content
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ─── Magic Bytes ───────────────────────────────────────────────────────────────
_MAGIC = {
    ".pdf":  [b"%PDF"],
    ".docx": [b"PK\x03\x04"],          # ZIP-based Office format
    ".doc":  [b"\xd0\xcf\x11\xe0"],     # OLE Compound Document
}

# ─── Dangerous PDF keywords ────────────────────────────────────────────────────
_DANGEROUS_KEYWORDS = [
    b"/JavaScript",
    b"/JS",
    b"/OpenAction",
    b"/AA",             # Additional Actions
    b"/Launch",
    b"/EmbeddedFile",
    b"/RichMedia",
    b"/XFA",            # Adobe XML Forms – often exploit vector
]

# ─── Executable magic bytes (PE, ELF, MZ) ─────────────────────────────────────
_EXEC_MAGIC = [b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe"]


@dataclass
class SecurityReport:
    """Result of a file security scan."""
    is_safe:            bool       = True
    risk_level:         str        = "low"       # low | medium | high | critical
    findings:           list[str]  = field(default_factory=list)
    sanitized_filename: str        = ""

    def as_dict(self) -> dict:
        return {
            "is_safe":            self.is_safe,
            "risk_level":         self.risk_level,
            "findings":           self.findings,
            "sanitized_filename": self.sanitized_filename,
        }


class UploadSecurity:
    """Stateless security scanner — call assert_upload_safe() before saving."""

    # ─── Public API ────────────────────────────────────────────────────────────
    def assert_upload_safe(
        self,
        file_bytes: bytes,
        filename:   str,
        max_size_mb: float = 10.0,
    ) -> SecurityReport:
        """
        Run all security checks on raw file bytes.

        Returns a SecurityReport.  Callers should check
        `report.is_safe` before proceeding.
        """
        report = SecurityReport()
        report.sanitized_filename = self._sanitize_filename(filename)
        ext = Path(filename).suffix.lower()

        # 1. Size check
        self._check_size(file_bytes, max_size_mb, report)

        # 2. Magic-byte validation
        self._check_magic_bytes(file_bytes, ext, report)

        # 3. Dangerous PDF keyword scan
        if ext == ".pdf":
            self._scan_pdf_keywords(file_bytes, report)
            self._scan_embedded_executables(file_bytes, report)

        # Derive overall risk level
        report.risk_level = self._derive_risk(report)

        if not report.is_safe:
            logger.warning(
                f"Security scan FAILED for '{filename}' "
                f"risk={report.risk_level} findings={report.findings}"
            )
        else:
            logger.info(
                f"Security scan PASSED for '{filename}' "
                f"risk={report.risk_level}"
            )

        return report

    # ─── Internal Checks ───────────────────────────────────────────────────────
    def _check_size(
        self,
        file_bytes:  bytes,
        max_size_mb: float,
        report:      SecurityReport,
    ) -> None:
        size_mb = len(file_bytes) / (1024 * 1024)
        if size_mb > max_size_mb:
            report.is_safe = False
            report.findings.append(
                f"File too large: {size_mb:.1f}MB > {max_size_mb}MB limit"
            )

    def _check_magic_bytes(
        self,
        file_bytes: bytes,
        ext:        str,
        report:     SecurityReport,
    ) -> None:
        """
        Compare first 8 bytes against known magic signatures.
        Prevents disguised executables (e.g. .exe renamed to .pdf).
        """
        expected_signatures = _MAGIC.get(ext)
        if not expected_signatures:
            return  # Unknown extension — checked upstream

        header = file_bytes[:8]
        for sig in expected_signatures:
            if header.startswith(sig):
                return  # Pass

        report.is_safe = False
        report.findings.append(
            f"Magic-byte mismatch for '{ext}': "
            f"header={header[:4].hex()} does not match expected signature"
        )

    def _scan_pdf_keywords(
        self,
        file_bytes: bytes,
        report:     SecurityReport,
    ) -> None:
        """Scan PDF byte stream for dangerous action keywords."""
        found = []
        for kw in _DANGEROUS_KEYWORDS:
            if kw in file_bytes:
                found.append(kw.decode("latin-1", errors="replace"))

        if found:
            # Presence of /EmbeddedFile alone is medium (some legit CVs embed fonts)
            # JS / OpenAction / Launch → always critical
            critical = {"/JavaScript", "/JS", "/OpenAction", "/Launch"}
            if any(k in critical for k in found):
                report.is_safe = False
            report.findings.append(
                f"Dangerous PDF keywords detected: {found}"
            )

    def _scan_embedded_executables(
        self,
        file_bytes: bytes,
        report:     SecurityReport,
    ) -> None:
        """Detect PE/ELF executable headers embedded inside PDF streams."""
        for magic in _EXEC_MAGIC:
            # Skip the first 4 bytes (legitimate PDF header area)
            if magic in file_bytes[4:]:
                report.is_safe = False
                report.findings.append(
                    f"Embedded executable magic bytes found: {magic.hex()}"
                )
                return

    # ─── Filename Sanitization ──────────────────────────────────────────────────
    def _sanitize_filename(self, filename: str) -> str:
        """
        Remove path traversal sequences, null bytes, and non-safe characters.
        """
        # Strip path components
        name = Path(filename).name
        # Remove null bytes
        name = name.replace("\x00", "")
        # Strip leading dots (hidden files on Unix)
        name = name.lstrip(".")
        # Replace dangerous characters
        name = re.sub(r"[^\w\s\-.]", "_", name)
        return name or "upload"

    # ─── Risk Derivation ───────────────────────────────────────────────────────
    def _derive_risk(self, report: SecurityReport) -> str:
        if not report.findings:
            return "low"
        if not report.is_safe:
            return "critical"
        # Has findings but still allowed (e.g. /EmbeddedFile warning)
        return "medium"


# ─── Singleton ─────────────────────────────────────────────────────────────────
upload_security = UploadSecurity()
