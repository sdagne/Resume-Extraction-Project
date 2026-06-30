# app/enhancement/resume_enhancer.py
"""
Enhancement Layer  —  Stage 6 of the extraction pipeline.

Controlled by environment variable:
    DOCEX_RESUME_ENHANCE=1   (default: 0 / off)

Sub-passes (all run in order when enabled):
  E1  Normalize          — clean whitespace, fix encoding artifacts
  E2  Section Recovery   — re-detect sections missed by the core parser
  E3  Headerless Exp     — infer experience entries with no section header
  E4  Field Repairs      — fix malformed dates, phones, emails
  E5  Skill Split        — explode comma / slash delimited skill strings
  E6  Skill Fuzzy        — fuzzy-match skills against taxonomy
  E7  Cert URL Mapper    — attach official URLs to known certifications
  E8  spaCy Entity Boost — use NER to recover missed names / orgs / dates
"""

import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ─── Config flag ───────────────────────────────────────────────────────────────
_ENHANCE_ENABLED = os.getenv("DOCEX_RESUME_ENHANCE", "0") == "1"

# ─── Known certification → URL mapping ────────────────────────────────────────
CERT_URL_MAP: dict[str, str] = {
    "aws certified solutions architect":    "https://aws.amazon.com/certification/certified-solutions-architect-associate/",
    "aws certified developer":              "https://aws.amazon.com/certification/certified-developer-associate/",
    "aws certified cloud practitioner":     "https://aws.amazon.com/certification/certified-cloud-practitioner/",
    "google cloud professional":            "https://cloud.google.com/certification",
    "azure fundamentals":                   "https://learn.microsoft.com/en-us/credentials/certifications/azure-fundamentals/",
    "azure developer associate":            "https://learn.microsoft.com/en-us/credentials/certifications/azure-developer/",
    "certified kubernetes administrator":   "https://www.cncf.io/certification/cka/",
    "ckad":                                 "https://www.cncf.io/certification/ckad/",
    "pmp":                                  "https://www.pmi.org/certifications/project-management-pmp",
    "cissp":                                "https://www.isc2.org/certifications/cissp",
    "comptia security+":                    "https://www.comptia.org/certifications/security",
    "comptia a+":                           "https://www.comptia.org/certifications/a",
    "tensorflow developer":                 "https://www.tensorflow.org/certificate",
    "professional scrum master":            "https://www.scrum.org/assessments/professional-scrum-master-i-certification",
    "certified scrum master":               "https://www.scrumalliance.org/get-certified/scrum-master-track/certified-scrummaster",
    "oracle certified professional":        "https://education.oracle.com/certification",
    "red hat certified engineer":           "https://www.redhat.com/en/services/certification/rhce",
}

# ─── Date patterns for repair ─────────────────────────────────────────────────
_DATE_REPAIRS = [
    (r"\b(\d{1,2})[/\-\.](\d{4})\b", r"\1/\2"),        # 3/2022 → 3/2022 (normalize sep)
    (r"\bPresant\b",                   "Present"),        # Common OCR typo
    (r"\bPresent\b",                   "Present"),        # Already correct
    (r"\bCurrent\b",                   "Present"),        # Normalize synonym
    (r"\bTill date\b",                 "Present"),
    (r"\bTill now\b",                  "Present"),
]

# ─── Phone number cleanup ─────────────────────────────────────────────────────
_PHONE_CLEANUP = re.compile(r"[^\d\+\-\(\)\s]")

# ─── Headerless experience indicators ─────────────────────────────────────────
_EXP_INDICATORS = re.compile(
    r"\b(engineer|developer|manager|analyst|consultant|designer|"
    r"architect|lead|senior|junior|intern|associate|director|"
    r"officer|head|specialist|coordinator|executive)\b",
    re.IGNORECASE,
)
_DATE_RANGE = re.compile(
    r"\b(\d{4}|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r".{0,15}(present|current|\d{4})\b",
    re.IGNORECASE,
)


@dataclass
class EnhancementReport:
    """Summary of all changes made by the enhancement layer."""
    enabled:         bool       = False
    passes_run:      list[str]  = field(default_factory=list)
    skills_split:    int        = 0
    skills_fuzzy:    int        = 0
    fields_repaired: int        = 0
    sections_recovered: int     = 0
    certs_mapped:    int        = 0
    entities_added:  int        = 0


class ResumeEnhancer:
    """
    Runs the configured enhancement sub-passes on an ExtractedResumeSchema.
    Returns (enhanced_schema, report).
    Call .enhance() — it is a no-op if DOCEX_RESUME_ENHANCE != "1".
    """

    def enhance(self, schema, full_text: str = "") -> tuple:
        """
        Entry point.

        Args:
            schema:     ExtractedResumeSchema (modified in-place on a deep copy)
            full_text:  Raw extracted text for entity boosting

        Returns:
            (enhanced_schema, EnhancementReport)
        """
        report = EnhancementReport(enabled=_ENHANCE_ENABLED)

        if not _ENHANCE_ENABLED:
            logger.debug("Enhancement layer is OFF (DOCEX_RESUME_ENHANCE=0)")
            return schema, report

        logger.info("Enhancement layer STARTING")
        enhanced = deepcopy(schema)

        # E1 — Normalize
        enhanced = self._e1_normalize(enhanced, report)

        # E2 — Section Recovery
        enhanced = self._e2_section_recovery(enhanced, full_text, report)

        # E3 — Headerless Experience
        enhanced = self._e3_headerless_experience(enhanced, full_text, report)

        # E4 — Field Repairs
        enhanced = self._e4_field_repairs(enhanced, report)

        # E5 — Skill Split
        enhanced = self._e5_skill_split(enhanced, report)

        # E6 — Skill Fuzzy Match
        enhanced = self._e6_skill_fuzzy(enhanced, report)

        # E7 — Cert URL Mapper
        enhanced = self._e7_cert_url_mapper(enhanced, report)

        # E8 — spaCy Entity Boost
        enhanced = self._e8_spacy_boost(enhanced, full_text, report)

        logger.info(
            f"Enhancement complete | passes={report.passes_run} | "
            f"skills_split={report.skills_split} | "
            f"fields_repaired={report.fields_repaired} | "
            f"certs_mapped={report.certs_mapped}"
        )

        return enhanced, report

    # ─── E1: Normalize ─────────────────────────────────────────────────────────
    def _e1_normalize(self, schema, report: EnhancementReport):
        report.passes_run.append("E1_normalize")

        # Clean whitespace in text fields
        if schema.contact:
            if hasattr(schema.contact, "name") and schema.contact.name:
                schema.contact.name = " ".join(schema.contact.name.split())
            if hasattr(schema.contact, "headline") and schema.contact.headline:
                schema.contact.headline = " ".join(
                    schema.contact.headline.split()
                )

        # Normalize summary
        if schema.summary:
            schema.summary = re.sub(r"\s+", " ", schema.summary).strip()

        return schema

    # ─── E2: Section Recovery ───────────────────────────────────────────────────
    def _e2_section_recovery(
        self, schema, full_text: str, report: EnhancementReport
    ):
        report.passes_run.append("E2_section_recovery")

        # If no summary found, look for "profile" / "objective" blocks in text
        if not schema.summary and full_text:
            summary_match = re.search(
                r"(?:professional\s+)?(?:summary|profile|objective|about\s+me)"
                r"\s*[:\n](.{50,600}?)(?:\n\n|\Z)",
                full_text,
                re.IGNORECASE | re.DOTALL,
            )
            if summary_match:
                candidate = summary_match.group(1).strip()
                if len(candidate) > 40:
                    schema.summary = candidate
                    report.sections_recovered += 1
                    logger.debug("E2: Recovered summary section")

        return schema

    # ─── E3: Headerless Experience ──────────────────────────────────────────────
    def _e3_headerless_experience(
        self, schema, full_text: str, report: EnhancementReport
    ):
        """
        If no experience entries were found but the text contains
        job-title + date-range patterns, attempt to create bare entries.
        """
        report.passes_run.append("E3_headerless_exp")

        if schema.experience or not full_text:
            return schema

        lines = full_text.splitlines()
        recovered = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or len(stripped) < 5:
                continue

            has_title    = bool(_EXP_INDICATORS.search(stripped))
            nearby_text  = " ".join(lines[max(0, i - 1):i + 3])
            has_dates    = bool(_DATE_RANGE.search(nearby_text))

            if has_title and has_dates:
                try:
                    from app.models.schemas.extracted_data import ExperienceItem
                    entry = ExperienceItem(job_title=stripped)
                    recovered.append(entry)
                except Exception:
                    pass

        if recovered:
            schema.experience = recovered
            report.sections_recovered += len(recovered)
            logger.debug(
                f"E3: Recovered {len(recovered)} headerless experience entries"
            )

        return schema

    # ─── E4: Field Repairs ─────────────────────────────────────────────────────
    def _e4_field_repairs(self, schema, report: EnhancementReport):
        report.passes_run.append("E4_field_repairs")

        # Repair dates in experience
        for exp in schema.experience:
            for attr in ("start_date", "end_date"):
                val = getattr(exp, attr, None)
                if val:
                    repaired = self._repair_date(val)
                    if repaired != val:
                        setattr(exp, attr, repaired)
                        report.fields_repaired += 1

        # Repair phone number
        if schema.contact and hasattr(schema.contact, "phone"):
            phone = schema.contact.phone or ""
            cleaned = _PHONE_CLEANUP.sub("", phone).strip()
            if cleaned != phone:
                schema.contact.phone = cleaned
                report.fields_repaired += 1

        # Repair email (lowercase)
        if schema.contact and hasattr(schema.contact, "email"):
            email = schema.contact.email or ""
            if email != email.lower():
                schema.contact.email = email.lower()
                report.fields_repaired += 1

        return schema

    def _repair_date(self, value: str) -> str:
        result = value
        for pattern, replacement in _DATE_REPAIRS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result.strip()

    # ─── E5: Skill Split ───────────────────────────────────────────────────────
    def _e5_skill_split(self, schema, report: EnhancementReport):
        """
        Explode skill strings like "Python, Java, SQL" or "React/Vue/Angular"
        into individual skill entries.
        """
        report.passes_run.append("E5_skill_split")

        if not hasattr(schema, "skills") or not schema.skills:
            return schema

        raw_skills = schema.skills.all or []
        expanded   = []

        for skill in raw_skills:
            # Split on common delimiters
            parts = re.split(r"[,;/|•·]", skill)
            for part in parts:
                cleaned = part.strip()
                if cleaned and len(cleaned) > 1:
                    expanded.append(cleaned)
                    if cleaned != skill:
                        report.skills_split += 1

        if expanded:
            schema.skills.all = list(dict.fromkeys(expanded))  # deduplicate, preserve order

        return schema

    # ─── E6: Skill Fuzzy Match ─────────────────────────────────────────────────
    def _e6_skill_fuzzy(self, schema, report: EnhancementReport):
        """
        Fuzzy-match skills against the taxonomy using RapidFuzz.
        Normalizes common variants (e.g. "ReactJS" → "React").
        """
        report.passes_run.append("E6_skill_fuzzy")

        if not hasattr(schema, "skills") or not schema.skills:
            return schema

        try:
            from rapidfuzz import process, fuzz
            from app.matching.skills_matcher import skills_matcher

            taxonomy = skills_matcher.get_all_canonical_skills()
            if not taxonomy:
                return schema

            normalized = []
            for skill in (schema.skills.all or []):
                match = process.extractOne(
                    skill,
                    taxonomy,
                    scorer=fuzz.token_sort_ratio,
                    score_cutoff=85,
                )
                if match:
                    normalized.append(match[0])
                    if match[0].lower() != skill.lower():
                        report.skills_fuzzy += 1
                else:
                    normalized.append(skill)

            schema.skills.all = list(dict.fromkeys(normalized))

        except Exception as e:
            logger.warning(f"E6 skill fuzzy failed: {e}")

        return schema

    # ─── E7: Cert URL Mapper ───────────────────────────────────────────────────
    def _e7_cert_url_mapper(self, schema, report: EnhancementReport):
        """
        Attach official URLs to known certifications found in the schema.
        """
        report.passes_run.append("E7_cert_url_mapper")

        if not hasattr(schema, "certifications") or not schema.certifications:
            return schema

        for cert in schema.certifications:
            if not cert.name:
                continue

            name_lower = cert.name.lower().strip()

            # Direct match
            url = CERT_URL_MAP.get(name_lower)

            # Partial match fallback
            if not url:
                for key, mapped_url in CERT_URL_MAP.items():
                    if key in name_lower or name_lower in key:
                        url = mapped_url
                        break

            if url and not getattr(cert, "url", None):
                cert.url = url
                report.certs_mapped += 1
                logger.debug(f"E7: Mapped cert '{cert.name}' → {url}")

        return schema

    # ─── E8: spaCy Entity Boost ────────────────────────────────────────────────
    def _e8_spacy_boost(
        self, schema, full_text: str, report: EnhancementReport
    ):
        """
        Use spaCy NER to recover entities that the rule-based parser missed:
        - PERSON  → fill contact.name if missing
        - ORG     → attach to nearest experience entry
        - DATE    → attach to nearest experience entry
        """
        report.passes_run.append("E8_spacy_boost")

        if not full_text:
            return schema

        try:
            from app.nlp.ner_engine import ner_engine

            entities = ner_engine.extract_entities(full_text[:4000])  # first 4k chars

            # Fill missing contact name
            if (
                entities.get("persons")
                and schema.contact
                and not getattr(schema.contact, "name", None)
            ):
                schema.contact.name = entities["persons"][0]
                report.entities_added += 1

            # Fill missing org in first experience entry
            if (
                entities.get("organizations")
                and schema.experience
                and not schema.experience[0].company
            ):
                schema.experience[0].company = entities["organizations"][0]
                report.entities_added += 1

        except Exception as e:
            logger.warning(f"E8 spaCy boost failed: {e}")

        return schema


# ─── Singleton ─────────────────────────────────────────────────────────────────
resume_enhancer = ResumeEnhancer()
