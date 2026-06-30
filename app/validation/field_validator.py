# app/validation/field_validator.py

import re
from typing import Optional
from datetime import datetime

from app.utils.logger import get_logger
from app.utils import regex_patterns as patterns
from app.utils.constants import Confidence

logger = get_logger(__name__)


class FieldValidator:
    """
    Validates individual extracted fields for correctness and format.

    Provides:
      - Format validation (email, phone, URL)
      - Value range validation (dates, GPA, experience years)
      - Completeness checks (required fields)
      - Sanitization (remove invalid characters)
    """

    # ─── Email ─────────────────────────────────────────────────────────────────
    def validate_email(self, email: Optional[str]) -> dict:
        """
        Validate an email address.

        Returns:
            {"valid": bool, "value": str | None, "reason": str}
        """
        if not email:
            return {"valid": False, "value": None, "reason": "empty"}

        email = email.strip().lower()

        # Basic format check
        if not patterns.EMAIL.match(email):
            return {"valid": False, "value": None, "reason": "invalid_format"}

        # Must have @ and domain with dot
        parts = email.split("@")
        if len(parts) != 2:
            return {"valid": False, "value": None, "reason": "missing_at"}

        domain = parts[1]
        if "." not in domain:
            return {"valid": False, "value": None, "reason": "invalid_domain"}

        # Domain TLD must be at least 2 chars
        tld = domain.split(".")[-1]
        if len(tld) < 2:
            return {"valid": False, "value": None, "reason": "invalid_tld"}

        # Check for obvious test/placeholder emails
        test_patterns = [
            r"^test@", r"@test\.", r"^example@",
            r"@example\.", r"^dummy@", r"^noreply@",
        ]
        for tp in test_patterns:
            if re.match(tp, email):
                return {
                    "valid": False,
                    "value": None,
                    "reason": "placeholder_email",
                }

        return {"valid": True, "value": email, "reason": "ok"}

    # ─── Phone ─────────────────────────────────────────────────────────────────
    def validate_phone(self, phone: Optional[str]) -> dict:
        """Validate and normalize a phone number."""
        if not phone:
            return {"valid": False, "value": None, "reason": "empty"}

        phone = phone.strip()

        # Extract digits only
        digits = re.sub(r"\D", "", phone)

        # Must have 7–15 digits (international standard)
        if len(digits) < 7:
            return {
                "valid": False,
                "value": None,
                "reason": "too_short",
            }
        if len(digits) > 15:
            return {
                "valid": False,
                "value": None,
                "reason": "too_long",
            }

        # Check for repeating digits (fake numbers like 1111111111)
        if len(set(digits)) <= 2:
            return {
                "valid": False,
                "value": None,
                "reason": "repeating_digits",
            }

        return {"valid": True, "value": phone, "reason": "ok"}

    # ─── URL ───────────────────────────────────────────────────────────────────
    def validate_url(self, url: Optional[str]) -> dict:
        """Validate a URL."""
        if not url:
            return {"valid": False, "value": None, "reason": "empty"}

        url = url.strip()

        # Must start with http/https or www
        if not re.match(r"^https?://|^www\.", url, re.IGNORECASE):
            return {"valid": False, "value": None, "reason": "missing_scheme"}

        # Add https if starts with www
        if url.startswith("www."):
            url = "https://" + url

        # Must contain a dot in domain
        domain_match = re.match(r"https?://([^/\s]+)", url)
        if not domain_match:
            return {"valid": False, "value": None, "reason": "invalid_domain"}

        domain = domain_match.group(1)
        if "." not in domain:
            return {"valid": False, "value": None, "reason": "no_tld"}

        return {"valid": True, "value": url, "reason": "ok"}

    # ─── LinkedIn URL ──────────────────────────────────────────────────────────
    def validate_linkedin(self, url: Optional[str]) -> dict:
        """Validate a LinkedIn profile URL."""
        if not url:
            return {"valid": False, "value": None, "reason": "empty"}

        url = url.strip()

        if "linkedin.com/in/" not in url.lower():
            return {
                "valid": False,
                "value": None,
                "reason": "not_linkedin_profile",
            }

        match = patterns.LINKEDIN.search(url)
        if not match:
            return {
                "valid": False,
                "value": None,
                "reason": "invalid_linkedin_format",
            }

        username = match.group(1)
        if len(username) < 3:
            return {
                "valid": False,
                "value": None,
                "reason": "username_too_short",
            }

        normalized = f"https://linkedin.com/in/{username}"
        return {"valid": True, "value": normalized, "reason": "ok"}

    # ─── Name ──────────────────────────────────────────────────────────────────
    def validate_name(self, name: Optional[str]) -> dict:
        """Validate a person's full name."""
        if not name:
            return {"valid": False, "value": None, "reason": "empty"}

        name = name.strip()

        # Too short
        if len(name) < 2:
            return {"valid": False, "value": None, "reason": "too_short"}

        # Too long
        if len(name) > 100:
            return {"valid": False, "value": None, "reason": "too_long"}

        # Must contain at least one letter
        if not any(c.isalpha() for c in name):
            return {"valid": False, "value": None, "reason": "no_letters"}

        # Contains digits (unlikely to be a real name)
        if any(c.isdigit() for c in name):
            return {
                "valid": False,
                "value": None,
                "reason": "contains_digits",
            }

        # Must have at least 2 parts (first + last name)
        parts = name.split()
        if len(parts) < 2:
            return {
                "valid": True,   # Single name is valid (some cultures)
                "value": name,
                "reason": "single_name",
            }

        return {"valid": True, "value": name, "reason": "ok"}

    # ─── Date ──────────────────────────────────────────────────────────────────
    def validate_date(self, date_str: Optional[str]) -> dict:
        """Validate a date string."""
        if not date_str:
            return {"valid": False, "value": None, "reason": "empty"}

        date_str = date_str.strip()

        # Present/current is always valid
        from app.utils.constants import PRESENT_KEYWORDS
        if date_str.lower() in PRESENT_KEYWORDS:
            return {"valid": True, "value": date_str, "reason": "present"}

        # Try to parse
        from app.nlp.date_parser import date_parser
        parsed = date_parser.parse_date_string(date_str)

        if not parsed:
            return {
                "valid": False,
                "value": None,
                "reason": "unparseable",
            }

        # Check reasonable date range (1950 – current year + 5)
        current_year = datetime.now().year
        if parsed.year < 1950:
            return {
                "valid": False,
                "value": None,
                "reason": "year_too_old",
            }
        if parsed.year > current_year + 5:
            return {
                "valid": False,
                "value": None,
                "reason": "year_in_future",
            }

        return {"valid": True, "value": date_str, "reason": "ok"}

    # ─── GPA ───────────────────────────────────────────────────────────────────
    def validate_gpa(self, gpa: Optional[str]) -> dict:
        """Validate a GPA value."""
        if not gpa:
            return {"valid": False, "value": None, "reason": "empty"}

        gpa = gpa.strip()

        # Extract numeric value
        num_match = re.search(r"(\d+(?:\.\d+)?)", gpa)
        if not num_match:
            return {
                "valid": False,
                "value": None,
                "reason": "non_numeric",
            }

        value = float(num_match.group(1))

        # Check scale (0–4 or 0–10 or 0–100)
        if "/" in gpa:
            scale_match = re.search(r"/\s*(\d+(?:\.\d+)?)", gpa)
            if scale_match:
                scale = float(scale_match.group(1))
                if value > scale:
                    return {
                        "valid": False,
                        "value": None,
                        "reason": "gpa_exceeds_scale",
                    }
        else:
            # Assume 4.0 scale
            if value > 4.0:
                if value > 10.0:
                    # Might be percentage (0–100)
                    if value > 100:
                        return {
                            "valid": False,
                            "value": None,
                            "reason": "invalid_gpa_value",
                        }

        return {"valid": True, "value": gpa, "reason": "ok"}

    # ─── Experience Years ──────────────────────────────────────────────────────
    def validate_experience_years(
        self,
        years: Optional[float],
    ) -> dict:
        """Validate total experience years."""
        if years is None:
            return {"valid": False, "value": None, "reason": "empty"}

        if not isinstance(years, (int, float)):
            return {
                "valid": False,
                "value": None,
                "reason": "non_numeric",
            }

        if years < 0:
            return {
                "valid": False,
                "value": None,
                "reason": "negative_value",
            }

        if years > 60:
            return {
                "valid": False,
                "value": None,
                "reason": "unrealistic_value",
            }

        return {"valid": True, "value": years, "reason": "ok"}

    # ─── Skill ─────────────────────────────────────────────────────────────────
    def validate_skill(self, skill: Optional[str]) -> dict:
        """Validate a skill entry."""
        if not skill:
            return {"valid": False, "value": None, "reason": "empty"}

        skill = skill.strip()

        if len(skill) < 2:
            return {"valid": False, "value": None, "reason": "too_short"}

        if len(skill) > 100:
            return {"valid": False, "value": None, "reason": "too_long"}

        if not any(c.isalpha() for c in skill):
            return {"valid": False, "value": None, "reason": "no_letters"}

        return {"valid": True, "value": skill, "reason": "ok"}

    # ─── Batch Validation ──────────────────────────────────────────────────────
    def validate_contact(self, contact: dict) -> dict:
        """
        Validate all contact fields at once.

        Returns dict with validation results per field.
        """
        results = {}

        if contact.get("email"):
            results["email"] = self.validate_email(contact["email"])
        if contact.get("phone"):
            results["phone"] = self.validate_phone(contact["phone"])
        if contact.get("full_name"):
            results["full_name"] = self.validate_name(contact["full_name"])
        if contact.get("linkedin"):
            results["linkedin"] = self.validate_linkedin(contact["linkedin"])
        if contact.get("github"):
            results["github"] = self.validate_url(contact["github"])
        if contact.get("website"):
            results["website"] = self.validate_url(contact["website"])

        return results

    def sanitize_field(self, value: Optional[str]) -> Optional[str]:
        """
        General-purpose field sanitizer.
        Removes control characters, excessive whitespace, etc.
        """
        if not value:
            return None

        # Remove control characters
        value = patterns.CONTROL_CHARS.sub("", value)

        # Normalize whitespace
        value = re.sub(r"\s+", " ", value).strip()

        return value if value else None


# ─── Singleton ─────────────────────────────────────────────────────────────────
field_validator = FieldValidator()
