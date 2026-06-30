# app/security/pdf_unlock.py
"""
PDF password detection and unlocking.

Strategy:
  1. Try opening with no password  (most PDFs)
  2. Try common blank / default passwords
  3. If owner-locked only (print/copy restrictions) → strip restrictions
  4. If user-locked (cannot read) → raise PDFEncryptedError

Requires: PyMuPDF (already in requirements.txt)
"""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ─── Common weak passwords to attempt ─────────────────────────────────────────
_COMMON_PASSWORDS = [
    "",           # blank
    "password",
    "1234",
    "12345",
    "123456",
    "adobe",
    "pdf",
    "owner",
    "user",
]


class PDFEncryptedError(Exception):
    """Raised when a PDF cannot be unlocked with available passwords."""
    pass


@dataclass
class UnlockResult:
    was_encrypted:  bool  = False
    was_unlocked:   bool  = False
    password_used:  str   = ""
    owner_locked:   bool  = False   # copy/print restrictions only
    unlocked_path:  Optional[Path] = None


class PDFUnlocker:
    """
    Attempts to unlock password-protected PDFs.
    Returns the unlocked file path (may be the same as input if not encrypted).
    """

    def unlock(
        self,
        file_path: Path,
        output_dir: Optional[Path] = None,
        extra_passwords: Optional[list[str]] = None,
    ) -> UnlockResult:
        """
        Attempt to unlock the PDF at `file_path`.

        Args:
            file_path:        Path to potentially encrypted PDF.
            output_dir:       Where to save the unlocked copy.
                              Defaults to file_path's parent.
            extra_passwords:  Caller-supplied passwords to try first.

        Returns:
            UnlockResult with the path to the (unlocked) PDF.

        Raises:
            PDFEncryptedError: If the PDF is user-locked and cannot be opened.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning("PyMuPDF not available – skipping PDF unlock step")
            return UnlockResult(unlocked_path=file_path)

        result = UnlockResult()

        doc = fitz.open(str(file_path))

        # Not encrypted at all
        if not doc.is_encrypted:
            doc.close()
            result.unlocked_path = file_path
            return result

        result.was_encrypted = True
        logger.info(f"Encrypted PDF detected: {file_path.name}")

        # Build password list: caller extras → common list
        passwords_to_try = list(extra_passwords or []) + _COMMON_PASSWORDS

        for pwd in passwords_to_try:
            auth_result = doc.authenticate(pwd)
            if auth_result:
                # auth_result: 1=user, 2=owner, 4=user+owner (PyMuPDF >= 1.23)
                result.was_unlocked = True
                result.password_used = pwd if pwd else "(blank)"
                result.owner_locked = (auth_result == 2)
                logger.info(
                    f"PDF unlocked: '{file_path.name}' | "
                    f"auth_type={auth_result} | "
                    f"owner_only={result.owner_locked}"
                )
                break

        if not result.was_unlocked:
            doc.close()
            raise PDFEncryptedError(
                f"Cannot unlock '{file_path.name}': "
                f"password not in common list. Manual decryption required."
            )

        # Save unlocked copy
        out_dir = output_dir or file_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        unlocked_path = out_dir / f"unlocked_{file_path.name}"

        doc.save(
            str(unlocked_path),
            encryption=fitz.PDF_ENCRYPT_NONE,  # strip all encryption
        )
        doc.close()

        result.unlocked_path = unlocked_path
        logger.info(f"Unlocked PDF saved: {unlocked_path.name}")
        return result


# ─── Singleton ─────────────────────────────────────────────────────────────────
pdf_unlocker = PDFUnlocker()
