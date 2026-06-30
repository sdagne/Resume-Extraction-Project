# app/validation/schema_validator.py

from typing import Optional

from pydantic import ValidationError

from app.utils.logger import get_logger
from app.utils.constants import Confidence
from app.models.schemas.extracted_data import ExtractedResumeSchema
from app.validation.field_validator import field_validator

logger = get_logger(__name__)


class SchemaValidator:
    """
    Validates and sanitizes a fully extracted resume schema.

    Responsibilities:
      - Run field-level validations on all extracted data
      - Fix invalid values (replace with None or corrected value)
      - Collect validation warnings
      - Ensure schema integrity (required fields, type checks)
      - Return clean, validated ExtractedResumeSchema
    """

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def validate(
        self,
        schema: ExtractedResumeSchema,
    ) -> tuple[ExtractedResumeSchema, list[str]]:
        """
        Validate and sanitize a complete extracted resume schema.

        Args:
            schema: The raw extracted resume schema

        Returns:
            (validated_schema, list_of_warnings)
        """
        warnings = []

        # ── Validate contact ──────────────────────────────────────────────────
        schema = self._validate_contact(schema, warnings)

        # ── Validate experience ────────────────────────────────────────────────
        schema = self._validate_experience(schema, warnings)

        # ── Validate education ─────────────────────────────────────────────────
        schema = self._validate_education(schema, warnings)

        # ── Validate skills ────────────────────────────────────────────────────
        schema = self._validate_skills(schema, warnings)

        # ── Validate certifications ────────────────────────────────────────────
        schema = self._validate_certifications(schema, warnings)

        # ── Validate summary ───────────────────────────────────────────────────
        schema = self._validate_summary(schema, warnings)

        # ── Validate total experience years ────────────────────────────────────
        schema = self._validate_experience_years(schema, warnings)

        # ── Cross-field validation ─────────────────────────────────────────────
        schema = self._cross_validate(schema, warnings)

        logger.info(
            f"Schema validation complete: "
            f"{len(warnings)} warnings"
        )

        return schema, warnings

    # ─── Contact Validation ────────────────────────────────────────────────────
    def _validate_contact(
        self,
        schema: ExtractedResumeSchema,
        warnings: list,
    ) -> ExtractedResumeSchema:
        """Validate and sanitize contact fields."""
        contact = schema.contact

        # Email
        if contact.email:
            result = field_validator.validate_email(contact.email)
            if not result["valid"]:
                warnings.append(
                    f"Invalid email '{contact.email}': {result['reason']}"
                )
                contact.email = None
            else:
                contact.email = result["value"]

        # Phone
        if contact.phone:
            result = field_validator.validate_phone(contact.phone)
            if not result["valid"]:
                warnings.append(
                    f"Invalid phone '{contact.phone}': {result['reason']}"
                )
                contact.phone = None

        # Name
        if contact.full_name:
            result = field_validator.validate_name(contact.full_name)
            if not result["valid"] and result["reason"] not in ("single_name",):
                warnings.append(
                    f"Suspicious name '{contact.full_name}': {result['reason']}"
                )
                if result["reason"] in ("contains_digits", "no_letters"):
                    contact.full_name = None

        # LinkedIn
        if contact.linkedin:
            result = field_validator.validate_linkedin(contact.linkedin)
            if not result["valid"]:
                warnings.append(
                    f"Invalid LinkedIn URL: {result['reason']}"
                )
                contact.linkedin = None
            else:
                contact.linkedin = result["value"]

        # GitHub
        if contact.github:
            result = field_validator.validate_url(contact.github)
            if not result["valid"]:
                warnings.append(
                    f"Invalid GitHub URL: {result['reason']}"
                )
                contact.github = None

        # Website
        if contact.website:
            result = field_validator.validate_url(contact.website)
            if not result["valid"]:
                warnings.append(
                    f"Invalid website URL: {result['reason']}"
                )
                contact.website = None

        # Sanitize text fields
        contact.full_name = field_validator.sanitize_field(contact.full_name)
        contact.city      = field_validator.sanitize_field(contact.city)
        contact.country   = field_validator.sanitize_field(contact.country)
        contact.address   = field_validator.sanitize_field(contact.address)

        schema.contact = contact
        return schema

    # ─── Experience Validation ─────────────────────────────────────────────────
    def _validate_experience(
        self,
        schema: ExtractedResumeSchema,
        warnings: list,
    ) -> ExtractedResumeSchema:
        """Validate experience entries."""
        valid_entries = []

        for i, exp in enumerate(schema.experience):
            entry_warnings = []

            # Validate dates
            if exp.start_date:
                result = field_validator.validate_date(exp.start_date)
                if not result["valid"]:
                    entry_warnings.append(
                        f"Experience[{i}]: invalid start_date '{exp.start_date}'"
                    )
                    exp.start_date = None

            if exp.end_date:
                result = field_validator.validate_date(exp.end_date)
                if not result["valid"]:
                    entry_warnings.append(
                        f"Experience[{i}]: invalid end_date '{exp.end_date}'"
                    )
                    exp.end_date = None

            # Validate date order
            if exp.start_date and exp.end_date and not exp.is_current:
                from app.nlp.date_parser import date_parser
                start = date_parser.parse_date_string(exp.start_date)
                end   = date_parser.parse_date_string(exp.end_date)
                if start and end and start > end:
                    entry_warnings.append(
                        f"Experience[{i}]: start_date after end_date"
                    )
                    exp.start_date, exp.end_date = exp.end_date, exp.start_date

            # Validate duration
            if exp.duration_years is not None:
                result = field_validator.validate_experience_years(
                    exp.duration_years
                )
                if not result["valid"]:
                    entry_warnings.append(
                        f"Experience[{i}]: invalid duration {exp.duration_years}"
                    )
                    exp.duration_years = None

            # Sanitize text fields
            exp.job_title   = field_validator.sanitize_field(exp.job_title)
            exp.company     = field_validator.sanitize_field(exp.company)
            exp.location    = field_validator.sanitize_field(exp.location)
            exp.description = field_validator.sanitize_field(exp.description)

            # Keep entry only if it has at least one meaningful field
            if exp.job_title or exp.company:
                valid_entries.append(exp)
                warnings.extend(entry_warnings)
            else:
                warnings.append(
                    f"Experience[{i}]: skipped — no job_title or company"
                )

        schema.experience = valid_entries
        return schema

    # ─── Education Validation ──────────────────────────────────────────────────
    def _validate_education(
        self,
        schema: ExtractedResumeSchema,
        warnings: list,
    ) -> ExtractedResumeSchema:
        """Validate education entries."""
        valid_entries = []

        for i, edu in enumerate(schema.education):
            # Validate GPA
            if edu.gpa:
                result = field_validator.validate_gpa(edu.gpa)
                if not result["valid"]:
                    warnings.append(
                        f"Education[{i}]: invalid GPA '{edu.gpa}': "
                        f"{result['reason']}"
                    )
                    edu.gpa = None

            # Validate graduation date
            if edu.graduation_date:
                result = field_validator.validate_date(edu.graduation_date)
                if not result["valid"]:
                    warnings.append(
                        f"Education[{i}]: invalid graduation_date "
                        f"'{edu.graduation_date}'"
                    )
                    edu.graduation_date = None

            # Sanitize text fields
            edu.degree         = field_validator.sanitize_field(edu.degree)
            edu.institution    = field_validator.sanitize_field(edu.institution)
            edu.field_of_study = field_validator.sanitize_field(edu.field_of_study)
            edu.location       = field_validator.sanitize_field(edu.location)

            if edu.degree or edu.institution:
                valid_entries.append(edu)
            else:
                warnings.append(
                    f"Education[{i}]: skipped — no degree or institution"
                )

        schema.education = valid_entries
        return schema

    # ─── Skills Validation ─────────────────────────────────────────────────────
    def _validate_skills(
        self,
        schema: ExtractedResumeSchema,
        warnings: list,
    ) -> ExtractedResumeSchema:
        """Validate and deduplicate skills."""
        from app.utils.helpers import deduplicate

        def clean_skill_list(skills: list[str]) -> list[str]:
            valid = []
            for skill in skills:
                result = field_validator.validate_skill(skill)
                if result["valid"]:
                    valid.append(result["value"])
            return deduplicate(valid)

        schema.skills.all        = clean_skill_list(schema.skills.all)
        schema.skills.technical  = clean_skill_list(schema.skills.technical)
        schema.skills.soft       = clean_skill_list(schema.skills.soft)
        schema.skills.tools      = clean_skill_list(schema.skills.tools)
        schema.skills.frameworks = clean_skill_list(schema.skills.frameworks)
        schema.skills.databases  = clean_skill_list(schema.skills.databases)

        if not schema.skills.all:
            warnings.append("No valid skills extracted")

        return schema

    # ─── Certifications Validation ─────────────────────────────────────────────
    def _validate_certifications(
        self,
        schema: ExtractedResumeSchema,
        warnings: list,
    ) -> ExtractedResumeSchema:
        """Validate certification entries."""
        valid_certs = []

        for i, cert in enumerate(schema.certifications):
            # Validate date
            if cert.date:
                result = field_validator.validate_date(cert.date)
                if not result["valid"]:
                    warnings.append(
                        f"Certification[{i}]: invalid date '{cert.date}'"
                    )
                    cert.date = None

            # Sanitize name
            cert.name   = field_validator.sanitize_field(cert.name)
            cert.issuer = field_validator.sanitize_field(cert.issuer)

            if cert.name:
                valid_certs.append(cert)
            else:
                warnings.append(
                    f"Certification[{i}]: skipped — no name"
                )

        schema.certifications = valid_certs
        return schema

    # ─── Summary Validation ────────────────────────────────────────────────────
    def _validate_summary(
        self,
        schema: ExtractedResumeSchema,
        warnings: list,
    ) -> ExtractedResumeSchema:
        """Validate professional summary."""
        if schema.summary:
            summary = schema.summary.strip()

            # Too short
            if len(summary) < 20:
                warnings.append(
                    f"Summary too short ({len(summary)} chars), discarding"
                )
                schema.summary = None

            # Too long — truncate
            elif len(summary) > 2000:
                warnings.append(
                    f"Summary too long ({len(summary)} chars), truncating"
                )
                schema.summary = summary[:2000].rsplit(" ", 1)[0] + "..."

        return schema

    # ─── Experience Years Validation ───────────────────────────────────────────
    def _validate_experience_years(
        self,
        schema: ExtractedResumeSchema,
        warnings: list,
    ) -> ExtractedResumeSchema:
        """Validate total experience years."""
        if schema.total_experience_years is not None:
            result = field_validator.validate_experience_years(
                schema.total_experience_years
            )
            if not result["valid"]:
                warnings.append(
                    f"Invalid total_experience_years: "
                    f"{schema.total_experience_years} — {result['reason']}"
                )
                schema.total_experience_years = None

        return schema

    # ─── Cross-Field Validation ────────────────────────────────────────────────
    def _cross_validate(
        self,
        schema: ExtractedResumeSchema,
        warnings: list,
    ) -> ExtractedResumeSchema:
        """
        Perform cross-field consistency checks.
        """
        # Check: if experience exists but no skills, warn
        if schema.experience and not schema.skills.all:
            warnings.append(
                "Experience found but no skills extracted — "
                "consider checking skills section"
            )

        # Check: education graduation date should not be in the future
        for edu in schema.education:
            if edu.graduation_date and edu.graduation_date != "Present":
                from app.nlp.date_parser import date_parser
                grad_dt = date_parser.parse_date_string(edu.graduation_date)
                if grad_dt and grad_dt.year > datetime.now().year + 6:
                    warnings.append(
                        f"Education graduation date {edu.graduation_date} "
                        f"seems far in the future"
                    )

        # Check: contact has at least one identifier
        contact = schema.contact
        if not contact.email and not contact.phone:
            warnings.append(
                "No email or phone found in contact section"
            )

        # Check: no name found
        if not contact.full_name:
            warnings.append("Candidate name not found")

        return schema

    # ─── Completeness Check ────────────────────────────────────────────────────
    def check_completeness(
        self,
        schema: ExtractedResumeSchema,
    ) -> dict:
        """
        Check how complete the extracted data is.

        Returns:
            {
                "score":    float,   # 0–1 completeness score
                "level":    str,     # "high" | "medium" | "low"
                "missing":  list[str],
                "present":  list[str],
            }
        """
        checks = {
            "name":          bool(schema.contact.full_name),
            "email":         bool(schema.contact.email),
            "phone":         bool(schema.contact.phone),
            "summary":       bool(schema.summary),
            "experience":    bool(schema.experience),
            "education":     bool(schema.education),
            "skills":        bool(schema.skills.all),
            "certifications":bool(schema.certifications),
            "linkedin":      bool(schema.contact.linkedin),
            "location":      bool(schema.contact.city or schema.contact.country),
        }

        weights = {
            "name":          0.20,
            "email":         0.15,
            "experience":    0.20,
            "education":     0.15,
            "skills":        0.15,
            "phone":         0.05,
            "summary":       0.05,
            "certifications":0.02,
            "linkedin":      0.02,
            "location":      0.01,
        }

        score   = sum(weights[k] for k, v in checks.items() if v)
        missing = [k for k, v in checks.items() if not v]
        present = [k for k, v in checks.items() if v]

        if score >= Confidence.HIGH_THRESHOLD:
            level = Confidence.HIGH
        elif score >= Confidence.MEDIUM_THRESHOLD:
            level = Confidence.MEDIUM
        else:
            level = Confidence.LOW

        return {
            "score":   round(score, 3),
            "level":   level,
            "missing": missing,
            "present": present,
        }


# ─── Singleton ─────────────────────────────────────────────────────────────────
schema_validator = SchemaValidator()
