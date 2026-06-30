# Certifications, licenses, accreditations
# app/extraction/certifications_extractor.py

import re
from typing import Optional

from app.utils.logger import get_logger
from app.nlp.text_cleaner import text_cleaner
from app.nlp.ner_engine   import ner_engine
from app.nlp.date_parser  import date_parser
from app.utils import regex_patterns as patterns

logger = get_logger(__name__)

# ─── Known Certification Issuers ───────────────────────────────────────────────
KNOWN_ISSUERS = [
    "aws", "amazon", "google", "microsoft", "oracle", "cisco",
    "comptia", "pmi", "isaca", "isc2", "ec-council", "linux foundation",
    "red hat", "vmware", "salesforce", "tableau", "databricks",
    "coursera", "udemy", "edx", "pluralsight", "linkedin learning",
]

# ─── Certification Keywords ────────────────────────────────────────────────────
CERT_KEYWORDS = [
    "certified", "certification", "certificate", "license",
    "accreditation", "credential", "professional", "associate",
    "practitioner", "specialist", "expert", "foundation",
]

# ─── Common Cert Abbreviations ─────────────────────────────────────────────────
CERT_ABBREVIATIONS = re.compile(
    r"\b(AWS|GCP|AZURE|CPA|CFA|PMP|CISSP|CEH|OSCP|CISM|CISA|"
    r"CCNA|CCNP|MCSA|MCSE|RHCE|RHCSA|OCA|OCP|ITIL|PRINCE2|"
    r"SCRUM|CSM|CSPO|PSM|SAFe|CKA|CKAD|CKS|GCP-ACE|AWS-SAA|"
    r"AWS-SAP|AWS-DEA|AWS-MLS|AZ-900|AZ-104|AZ-204|DP-900)\b"
)


class CertificationsExtractor:
    """
    Extracts professional certifications from resume text.

    Each entry contains:
      - Certification name
      - Issuing organization
      - Date obtained
      - Expiry date (if mentioned)
      - Credential ID (if mentioned)
    """

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def extract(self, section_text: str) -> list[dict]:
        """
        Extract all certifications from section text.

        Returns:
            List of certification dicts.
        """
        if not section_text or not section_text.strip():
            return []

        cleaned = text_cleaner.clean(section_text)
        lines   = text_cleaner.extract_clean_lines(cleaned)

        certifications = []
        current_cert   = None

        for line in lines:
            # Skip section headers
            if self._is_section_header(line):
                continue

            # Check if line starts a new certification
            if self._is_cert_line(line):
                if current_cert:
                    certifications.append(current_cert)
                current_cert = self._parse_cert_line(line)
            elif current_cert:
                # Additional info for current cert (date, issuer, ID)
                self._enrich_cert(current_cert, line)

        # Don't forget the last cert
        if current_cert:
            certifications.append(current_cert)

        # Post-process: extract any remaining fields
        certifications = [
            self._post_process(cert)
            for cert in certifications
            if cert.get("name")
        ]

        logger.info(f"Extracted {len(certifications)} certifications")
        return certifications

    # ─── Line Detection ────────────────────────────────────────────────────────
    def _is_cert_line(self, line: str) -> bool:
        """Check if a line describes a certification."""
        line_lower = line.lower()

        # Contains certification keywords
        if any(kw in line_lower for kw in CERT_KEYWORDS):
            return True

        # Contains known abbreviations
        if CERT_ABBREVIATIONS.search(line):
            return True

        # Contains known issuer
        if any(issuer in line_lower for issuer in KNOWN_ISSUERS):
            return True

        return False

    def _is_section_header(self, text: str) -> bool:
        """Check if text is a section header."""
        from app.utils.constants import SECTION_KEYWORDS
        normalized = text.lower().strip().rstrip(":")
        for keywords in SECTION_KEYWORDS.values():
            if normalized in [k.lower() for k in keywords]:
                return True
        return False

    # ─── Cert Parsing ──────────────────────────────────────────────────────────
    def _parse_cert_line(self, line: str) -> dict:
        """Parse a single certification line into a structured dict."""
        cert = {
            "name":          None,
            "issuer":        None,
            "date":          None,
            "expiry_date":   None,
            "credential_id": None,
        }

        # ── Extract date ───────────────────────────────────────────────────────
        date_match = patterns.MONTH_YEAR.search(line)
        if date_match:
            raw_date    = date_match.group(0)
            cert["date"] = date_parser.normalize_date(raw_date)
            # Remove date from line for cleaner name extraction
            line = line.replace(raw_date, "").strip()
        else:
            year_match = patterns.YEAR.search(line)
            if year_match:
                cert["date"] = year_match.group(0)
                line = line.replace(year_match.group(0), "").strip()

        # ── Extract issuer ─────────────────────────────────────────────────────
        line_lower = line.lower()
        for issuer in KNOWN_ISSUERS:
            if issuer in line_lower:
                cert["issuer"] = issuer.title()
                break

        # ── Extract credential ID ──────────────────────────────────────────────
        cred_pattern = re.compile(
            r"(?:credential\s*id|cert\s*id|license\s*no\.?|id)[:\s#]+([A-Z0-9\-]+)",
            re.IGNORECASE,
        )
        cred_match = cred_pattern.search(line)
        if cred_match:
            cert["credential_id"] = cred_match.group(1).strip()
            line = cred_pattern.sub("", line).strip()

        # ── Extract cert name ──────────────────────────────────────────────────
        # Clean up separators and extra whitespace
        name = re.sub(r"\s*[-|–·]\s*", " ", line)
        name = re.sub(r"\s+", " ", name).strip()
        name = re.sub(r"[,;]+$", "", name).strip()

        if name and len(name) > 3:
            cert["name"] = name

        # ── Try abbreviation as name if no name found ──────────────────────────
        if not cert["name"]:
            abbr_match = CERT_ABBREVIATIONS.search(line)
            if abbr_match:
                cert["name"] = abbr_match.group(0)

        return cert

    def _enrich_cert(self, cert: dict, line: str) -> None:
        """
        Add additional information to an existing cert entry
        from a following line.
        """
        line_lower = line.lower()

        # Issuer
        if not cert["issuer"]:
            for issuer in KNOWN_ISSUERS:
                if issuer in line_lower:
                    cert["issuer"] = issuer.title()
                    break

        # Date
        if not cert["date"]:
            date_match = patterns.MONTH_YEAR.search(line)
            if date_match:
                cert["date"] = date_parser.normalize_date(date_match.group(0))

        # Expiry
        if not cert["expiry_date"]:
            expiry_pattern = re.compile(
                r"(?:expir|valid\s*until|expires?)[:\s]+(.+)",
                re.IGNORECASE,
            )
            exp_match = expiry_pattern.search(line)
            if exp_match:
                cert["expiry_date"] = date_parser.normalize_date(
                    exp_match.group(1).strip()
                )

        # Credential ID
        if not cert["credential_id"]:
            cred_pattern = re.compile(
                r"(?:credential\s*id|cert\s*id|id)[:\s#]+([A-Z0-9\-]+)",
                re.IGNORECASE,
            )
            cred_match = cred_pattern.search(line)
            if cred_match:
                cert["credential_id"] = cred_match.group(1).strip()

    def _post_process(self, cert: dict) -> dict:
        """Clean up and validate a certification entry."""
        # Clean name
        if cert.get("name"):
            cert["name"] = cert["name"].strip()
            # Remove trailing punctuation
            cert["name"] = re.sub(r"[,;:]+$", "", cert["name"]).strip()

        # Try to extract issuer from name if not found
        if not cert.get("issuer") and cert.get("name"):
            name_lower = cert["name"].lower()
            for issuer in KNOWN_ISSUERS:
                if issuer in name_lower:
                    cert["issuer"] = issuer.title()
                    break

        return cert


# ─── Singleton ─────────────────────────────────────────────────────────────────
certifications_extractor = CertificationsExtractor()
