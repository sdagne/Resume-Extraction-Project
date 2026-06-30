# app/extraction/contact_extractor.py

import re
from typing import Optional

from app.utils.logger import get_logger
from app.utils import regex_patterns as patterns
from app.nlp.text_cleaner import text_cleaner
from app.nlp.ner_engine   import ner_engine

logger = get_logger(__name__)


class ContactExtractor:
    """
    Extracts contact information from resume text:
      - Full name
      - Email address
      - Phone number
      - LinkedIn URL
      - GitHub URL
      - Personal website
      - Address / City / Country

    Strategy:
      - Regex for structured fields (email, phone, URLs)
      - spaCy NER for name and location
      - Positional heuristic: contact info is usually at the top
    """

    # ─── Country / City Keywords ───────────────────────────────────────────────
    COUNTRY_KEYWORDS = {
        "usa", "united states", "us", "uk", "united kingdom",
        "canada", "australia", "germany", "france", "india",
        "switzerland", "austria", "netherlands", "sweden",
        "norway", "denmark", "finland", "spain", "italy",
        "singapore", "uae", "dubai", "new zealand", "ireland",
        "pakistan", "bangladesh", "nigeria", "south africa",
    }

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def extract(
        self,
        text: str,
        text_blocks: Optional[list[dict]] = None,
    ) -> dict:
        """
        Extract all contact information from text.

        Args:
            text:        Full text of contact section (or full resume)
            text_blocks: Optional blocks for positional analysis

        Returns:
            {
                "full_name":  str | None,
                "email":      str | None,
                "phone":      str | None,
                "linkedin":   str | None,
                "github":     str | None,
                "website":    str | None,
                "address":    str | None,
                "city":       str | None,
                "country":    str | None,
                "confidence": float,
            }
        """
        # Use top portion of text for contact extraction
        contact_text = self._get_contact_region(text, text_blocks)

        result = {
            "full_name": None,
            "email":     None,
            "phone":     None,
            "linkedin":  None,
            "github":    None,
            "website":   None,
            "address":   None,
            "city":      None,
            "country":   None,
        }

        # ── Email ──────────────────────────────────────────────────────────────
        result["email"] = self._extract_email(contact_text)

        # ── Phone ──────────────────────────────────────────────────────────────
        result["phone"] = self._extract_phone(contact_text)

        # ── LinkedIn ───────────────────────────────────────────────────────────
        result["linkedin"] = self._extract_linkedin(contact_text)

        # ── GitHub ─────────────────────────────────────────────────────────────
        result["github"] = self._extract_github(contact_text)

        # ── Website ────────────────────────────────────────────────────────────
        result["website"] = self._extract_website(
            contact_text,
            exclude_linkedin=result["linkedin"],
            exclude_github=result["github"],
        )

        # ── Full Name ──────────────────────────────────────────────────────────
        result["full_name"] = self._extract_name(
            contact_text, text_blocks
        )

        # ── Location ───────────────────────────────────────────────────────────
        location = self._extract_location(contact_text)
        result["city"]    = location.get("city")
        result["country"] = location.get("country")
        result["address"] = location.get("address")

        # ── Confidence ─────────────────────────────────────────────────────────
        result["confidence"] = self._calculate_confidence(result)

        logger.info(
            f"Contact extracted: name='{result['full_name']}', "
            f"email='{result['email']}', "
            f"phone='{result['phone']}'"
        )
        return result

    # ─── Email ─────────────────────────────────────────────────────────────────
    def _extract_email(self, text: str) -> Optional[str]:
        """Extract and validate email address."""
        match = patterns.EMAIL.search(text)
        if match:
            email = match.group(0).lower().strip()
            # Basic validation
            if "@" in email and "." in email.split("@")[-1]:
                return email
        return None

    # ─── Phone ─────────────────────────────────────────────────────────────────
    def _extract_phone(self, text: str) -> Optional[str]:
        """
        Extract phone number and normalize to a clean format.
        Handles international formats.
        """
        match = patterns.PHONE.search(text)
        if not match:
            return None

        raw = match.group(0).strip()

        # Clean up the phone number
        cleaned = re.sub(r"[^\d+\-() ]", "", raw).strip()

        # Validate: must have at least 7 digits
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) < 7:
            return None

        return cleaned

    # ─── LinkedIn ──────────────────────────────────────────────────────────────
    def _extract_linkedin(self, text: str) -> Optional[str]:
        """Extract LinkedIn profile URL."""
        match = patterns.LINKEDIN.search(text)
        if match:
            username = match.group(1)
            return f"https://linkedin.com/in/{username}"

        # Try to find partial LinkedIn mention
        li_match = re.search(
            r"linkedin[:\s/]+([a-zA-Z0-9\-_/]+)",
            text,
            re.IGNORECASE,
        )
        if li_match:
            return f"https://linkedin.com/in/{li_match.group(1).strip('/')}"

        return None

    # ─── GitHub ────────────────────────────────────────────────────────────────
    def _extract_github(self, text: str) -> Optional[str]:
        """Extract GitHub profile URL."""
        match = patterns.GITHUB.search(text)
        if match:
            username = match.group(1)
            return f"https://github.com/{username}"

        # Try partial GitHub mention
        gh_match = re.search(
            r"github[:\s/]+([a-zA-Z0-9\-_]+)",
            text,
            re.IGNORECASE,
        )
        if gh_match:
            return f"https://github.com/{gh_match.group(1)}"

        return None

    # ─── Website ───────────────────────────────────────────────────────────────
    def _extract_website(
        self,
        text: str,
        exclude_linkedin: Optional[str] = None,
        exclude_github:   Optional[str] = None,
    ) -> Optional[str]:
        """Extract personal website URL (excluding LinkedIn/GitHub)."""
        # Find all URLs
        url_pattern = re.compile(
            r"https?://[^\s,;)>\"']+|www\.[^\s,;)>\"']+",
            re.IGNORECASE,
        )

        for match in url_pattern.finditer(text):
            url = match.group(0)
            url_lower = url.lower()

            # Skip social media
            if any(skip in url_lower for skip in [
                "linkedin", "github", "twitter", "facebook",
                "instagram", "youtube",
            ]):
                continue

            # Add https if missing
            if url.startswith("www."):
                url = "https://" + url

            return url

        return None

    # ─── Name ──────────────────────────────────────────────────────────────────
    def _extract_name(
        self,
        text: str,
        text_blocks: Optional[list[dict]] = None,
    ) -> Optional[str]:
        """
        Extract candidate full name using multiple strategies:
          1. Largest font block at top of document
          2. spaCy PERSON entity
          3. First non-contact line heuristic
        """
        # Strategy 1: Largest font block at top
        if text_blocks:
            name = self._name_from_blocks(text_blocks)
            if name:
                return name

        # Strategy 2: spaCy NER
        name = ner_engine.extract_person_name(text)
        if name:
            return name

        # Strategy 3: First meaningful line heuristic
        name = self._name_from_first_line(text)
        return name

    def _name_from_blocks(
        self,
        text_blocks: list[dict],
    ) -> Optional[str]:
        """
        Find name from the block with the largest font size
        in the top portion of the document.
        """
        # Look at first 5 blocks only
        top_blocks = text_blocks[:5]

        best_block = None
        best_size  = 0.0

        for block in top_blocks:
            text      = block.get("text", "").strip()
            font_size = block.get("font_size", 0.0)

            if not text or len(text) > 60:
                continue

            # Skip if it looks like contact info
            if (
                patterns.EMAIL.search(text) or
                patterns.PHONE.search(text) or
                patterns.LINKEDIN.search(text) or
                patterns.GITHUB.search(text)
            ):
                continue

            # Skip if it looks like a section header keyword
            if self._is_section_keyword(text):
                continue

            words = text.split()
            if 1 <= len(words) <= 5 and font_size > best_size:
                best_size  = font_size
                best_block = block

        if best_block:
            return self._clean_name(best_block["text"])

        return None

    def _name_from_first_line(self, text: str) -> Optional[str]:
        """
        Extract name from the first meaningful line of text.
        Used as last-resort fallback.
        """
        lines = text_cleaner.extract_clean_lines(text, min_length=3)

        for line in lines[:5]:
            # Skip lines with contact info
            if (
                patterns.EMAIL.search(line) or
                patterns.PHONE.search(line) or
                "@" in line or
                "http" in line.lower()
            ):
                continue

            words = line.split()
            if 2 <= len(words) <= 4:
                # Check if words look like name parts (capitalized)
                if all(w[0].isupper() for w in words if w.isalpha()):
                    return self._clean_name(line)

        return None

    def _clean_name(self, name: str) -> str:
        """Clean and normalize a name string."""
        # Remove common prefixes/suffixes
        name = re.sub(
            r"^(Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)\s+",
            "",
            name,
            flags=re.IGNORECASE,
        )
        # Remove trailing credentials
        name = re.sub(
            r",?\s*(PhD|MD|MBA|MSc|BSc|BA|MA|CPA|CFA|PMP)\.?$",
            "",
            name,
            flags=re.IGNORECASE,
        )
        return name.strip()

    # ─── Location ──────────────────────────────────────────────────────────────
    def _extract_location(self, text: str) -> dict:
        """
        Extract city, country, and address from contact text.
        Uses NER + pattern matching + keyword lookup.
        """
        result = {"city": None, "country": None, "address": None}

        # ── Strategy 1: NER-based location extraction ─────────────────────────
        entities  = ner_engine.extract_entities(text)
        locations = entities.get("locations", [])

        if locations:
            # Try to classify locations as city vs country
            for loc in locations:
                loc_lower = loc.lower().strip()
                if loc_lower in self.COUNTRY_KEYWORDS:
                    if not result["country"]:
                        result["country"] = loc.title()
                elif not result["city"]:
                    result["city"] = loc

        # ── Strategy 2: Pattern-based address detection ───────────────────────
        address = self._extract_address_pattern(text)
        if address:
            result["address"] = address
            # Try to extract city/country from address
            if not result["city"] or not result["country"]:
                parsed = self._parse_address(address)
                if not result["city"]:
                    result["city"] = parsed.get("city")
                if not result["country"]:
                    result["country"] = parsed.get("country")

        return result

    def _extract_address_pattern(self, text: str) -> Optional[str]:
        """
        Extract address using common address patterns.
        Looks for street numbers, zip codes, etc.
        """
        # Pattern: number + street name
        street_pattern = re.compile(
            r"\d+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
            r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|"
            r"Boulevard|Blvd|Court|Ct|Place|Pl)\b",
            re.IGNORECASE,
        )
        match = street_pattern.search(text)
        if match:
            return match.group(0).strip()

        # Pattern: City, State ZIP (US format)
        us_pattern = re.compile(
            r"[A-Z][a-zA-Z\s]+,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?",
        )
        match = us_pattern.search(text)
        if match:
            return match.group(0).strip()

        return None

    def _parse_address(self, address: str) -> dict:
        """Parse city and country from an address string."""
        result = {"city": None, "country": None}

        # Check for country keywords
        addr_lower = address.lower()
        for country in self.COUNTRY_KEYWORDS:
            if country in addr_lower:
                result["country"] = country.title()
                break

        # Extract city (first capitalized word group before comma)
        city_match = re.match(r"^([A-Z][a-zA-Z\s]+?)(?:,|\s{2,}|\d)", address)
        if city_match:
            result["city"] = city_match.group(1).strip()

        return result

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _get_contact_region(
        self,
        text: str,
        text_blocks: Optional[list[dict]],
    ) -> str:
        """
        Get the contact region text.
        Uses top 30% of text or first 500 chars as heuristic.
        """
        # If we have the full text, use first 600 chars for contact
        if len(text) > 600:
            return text[:600]
        return text

    def _is_section_keyword(self, text: str) -> bool:
        """Check if text is a known section keyword."""
        from app.utils.constants import SECTION_KEYWORDS
        normalized = text.lower().strip().rstrip(":")
        for keywords in SECTION_KEYWORDS.values():
            if normalized in [k.lower() for k in keywords]:
                return True
        return False

    def _calculate_confidence(self, result: dict) -> float:
        """
        Calculate confidence score based on how many
        contact fields were successfully extracted.
        """
        field_weights = {
            "full_name": 0.30,
            "email":     0.25,
            "phone":     0.20,
            "linkedin":  0.10,
            "city":      0.10,
            "country":   0.05,
        }
        score = sum(
            weight
            for field, weight in field_weights.items()
            if result.get(field)
        )
        return round(score, 3)


# ─── Singleton ─────────────────────────────────────────────────────────────────
contact_extractor = ContactExtractor()
