# app/extraction/education_extractor.py

import re
from typing import Optional

from app.utils.logger import get_logger
from app.utils import regex_patterns as patterns
from app.nlp.text_cleaner import text_cleaner
from app.nlp.ner_engine   import ner_engine
from app.nlp.date_parser  import date_parser

logger = get_logger(__name__)

# ─── Degree Rankings (for highest degree detection) ────────────────────────────
DEGREE_RANK = {
    "phd": 7, "doctorate": 7, "doctor": 7,
    "mba": 6, "master": 5, "msc": 5, "ma": 5, "meng": 5, "mtech": 5,
    "bachelor": 4, "bsc": 4, "ba": 4, "be": 4, "btech": 4, "beng": 4,
    "associate": 3,
    "diploma": 2,
    "certificate": 1,
    "high school": 0, "secondary": 0,
}

# ─── Field of Study Keywords ───────────────────────────────────────────────────
FIELD_OF_STUDY_KEYWORDS = [
    "computer science", "information technology", "software engineering",
    "electrical engineering", "mechanical engineering", "civil engineering",
    "data science", "artificial intelligence", "machine learning",
    "business administration", "finance", "economics", "accounting",
    "mathematics", "statistics", "physics", "chemistry", "biology",
    "psychology", "sociology", "communications", "marketing",
    "human resources", "information systems", "cybersecurity",
    "network engineering", "cloud computing",
]


class EducationExtractor:
    """
    Extracts education entries from resume text.

    Each entry contains:
      - Degree type
      - Field of study
      - Institution name
      - Location
      - Start date / Graduation date
      - GPA (if present)
    """

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def extract(self, section_text: str) -> list[dict]:
        """
        Extract all education entries from section text.

        Returns:
            List of education dicts, highest degree first.
        """
        if not section_text or not section_text.strip():
            return []

        cleaned = text_cleaner.clean(section_text)

        # Split into individual education entries
        entries = self._split_into_entries(cleaned)

        education = []
        for entry_text in entries:
            if not entry_text.strip():
                continue
            edu = self._parse_entry(entry_text)
            if edu and (edu.get("degree") or edu.get("institution")):
                education.append(edu)

        # Sort by degree rank (highest first)
        education = self._sort_by_rank(education)

        logger.info(f"Extracted {len(education)} education entries")
        return education

    # ─── Entry Splitting ───────────────────────────────────────────────────────
    def _split_into_entries(self, text: str) -> list[str]:
        """
        Split education section into individual entries.
        Boundaries: degree keywords, institution names, date ranges.
        """
        lines   = text.splitlines()
        entries = []
        current = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                if current:
                    next_lines = [
                        l.strip() for l in lines[i+1:i+3]
                        if l.strip()
                    ]
                    if next_lines and self._is_edu_entry_start(next_lines[0]):
                        entries.append("\n".join(current))
                        current = []
                continue

            if current and self._is_edu_entry_start(stripped):
                entries.append("\n".join(current))
                current = [stripped]
            else:
                current.append(stripped)

        if current:
            entries.append("\n".join(current))

        return entries if entries else [text]

    def _is_edu_entry_start(self, line: str) -> bool:
        """Check if a line signals a new education entry."""
        # Has a degree keyword
        if patterns.DEGREE.search(line):
            return True
        # Has a date
        if patterns.DATE_RANGE.search(line) or patterns.YEAR.search(line):
            return True
        return False

    # ─── Entry Parsing ─────────────────────────────────────────────────────────
    def _parse_entry(self, entry_text: str) -> dict:
        """Parse a single education entry."""
        lines = [l.strip() for l in entry_text.splitlines() if l.strip()]
        if not lines:
            return {}

        result = {
            "degree":          None,
            "field_of_study":  None,
            "institution":     None,
            "location":        None,
            "start_date":      None,
            "graduation_date": None,
            "gpa":             None,
        }

        # ── Step 1: Extract dates ──────────────────────────────────────────────
        date_info, date_idx = self._extract_dates(lines)
        if date_info:
            result["start_date"]      = date_info.get("start_date")
            result["graduation_date"] = date_info.get("end_date")

        # ── Step 2: Extract GPA ────────────────────────────────────────────────
        result["gpa"] = self._extract_gpa(entry_text)

        # ── Step 3: Extract degree and field of study ──────────────────────────
        for line in lines:
            if patterns.DEGREE.search(line):
                degree_info = self._parse_degree_line(line)
                if degree_info.get("degree") and not result["degree"]:
                    result["degree"]         = degree_info["degree"]
                    result["field_of_study"] = degree_info.get("field_of_study")
                break

        # ── Step 4: Extract field of study (if not found with degree) ──────────
        if not result["field_of_study"]:
            result["field_of_study"] = self._extract_field_of_study(entry_text)

        # ── Step 5: Extract institution ────────────────────────────────────────
        result["institution"] = self._extract_institution(
            lines, skip_degree_line=result["degree"] is not None
        )

        # ── Step 6: Extract location ───────────────────────────────────────────
        locs = ner_engine.extract_locations(entry_text)
        if locs:
            result["location"] = locs[0]

        return result

    # ─── Date Extraction ───────────────────────────────────────────────────────
    def _extract_dates(
        self,
        lines: list[str],
    ) -> tuple[Optional[dict], Optional[int]]:
        """Extract graduation date or date range from lines."""
        for i, line in enumerate(lines):
            if patterns.DATE_RANGE.search(line):
                info = date_parser.parse_date_range(line)
                if info.get("start_date") or info.get("end_date"):
                    return info, i

        # Single year (graduation year)
        for i, line in enumerate(lines):
            year_match = patterns.YEAR.search(line)
            if year_match:
                year = year_match.group(0)
                return {
                    "start_date": None,
                    "end_date":   year,
                    "is_current": False,
                }, i

        return None, None

    # ─── Degree Parsing ────────────────────────────────────────────────────────
    def _parse_degree_line(self, line: str) -> dict:
        """
        Parse a line containing degree information.
        Handles formats like:
          - "Bachelor of Science in Computer Science"
          - "B.Sc. Computer Science"
          - "Master of Business Administration (MBA)"
        """
        result = {"degree": None, "field_of_study": None}

        # Extract degree abbreviation/name
        degree_match = patterns.DEGREE.search(line)
        if degree_match:
            result["degree"] = self._normalize_degree(degree_match.group(0))

        # Extract field of study
        # Pattern: "in X", "of X", "(X)"
        field_patterns = [
            re.compile(r"\bin\s+([A-Za-z\s&]+?)(?:\s*,|\s*\(|\s*$)", re.IGNORECASE),
            re.compile(r"\bof\s+([A-Za-z\s&]+?)(?:\s*,|\s*\(|\s*$)", re.IGNORECASE),
            re.compile(r"\(([A-Za-z\s&]+?)\)",),
        ]

        for fp in field_patterns:
            match = fp.search(line)
            if match:
                field = match.group(1).strip()
                if len(field) > 2 and field.lower() not in [
                    "science", "arts", "technology", "engineering"
                ]:
                    result["field_of_study"] = field.title()
                    break

        # Check against known fields
        if not result["field_of_study"]:
            line_lower = line.lower()
            for field in FIELD_OF_STUDY_KEYWORDS:
                if field in line_lower:
                    result["field_of_study"] = field.title()
                    break

        return result

    def _normalize_degree(self, degree_str: str) -> str:
        """Normalize degree abbreviations to full names."""
        degree_map = {
            "b.sc": "Bachelor of Science",
            "bsc":  "Bachelor of Science",
            "b.s":  "Bachelor of Science",
            "bs":   "Bachelor of Science",
            "b.a":  "Bachelor of Arts",
            "ba":   "Bachelor of Arts",
            "b.e":  "Bachelor of Engineering",
            "be":   "Bachelor of Engineering",
            "b.tech": "Bachelor of Technology",
            "btech":  "Bachelor of Technology",
            "m.sc": "Master of Science",
            "msc":  "Master of Science",
            "m.s":  "Master of Science",
            "ms":   "Master of Science",
            "m.a":  "Master of Arts",
            "ma":   "Master of Arts",
            "mba":  "Master of Business Administration",
            "m.b.a":"Master of Business Administration",
            "m.e":  "Master of Engineering",
            "me":   "Master of Engineering",
            "m.tech": "Master of Technology",
            "mtech":  "Master of Technology",
            "ph.d": "Doctor of Philosophy",
            "phd":  "Doctor of Philosophy",
            "ph.d.":"Doctor of Philosophy",
        }
        key = degree_str.lower().strip().rstrip(".")
        return degree_map.get(key, degree_str.title())

    # ─── Field of Study ────────────────────────────────────────────────────────
    def _extract_field_of_study(self, text: str) -> Optional[str]:
        """Extract field of study from text using keyword matching."""
        text_lower = text.lower()
        for field in FIELD_OF_STUDY_KEYWORDS:
            if field in text_lower:
                return field.title()
        return None

    # ─── Institution ───────────────────────────────────────────────────────────
    def _extract_institution(
        self,
        lines: list[str],
        skip_degree_line: bool = False,
    ) -> Optional[str]:
        """
        Extract institution name using NER + keyword heuristics.
        """
        institution_keywords = [
            "university", "college", "institute", "school",
            "academy", "polytechnic", "faculty", "campus",
        ]

        for line in lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in institution_keywords):
                # Clean up the institution name
                return self._clean_institution(line)

        # NER fallback
        full_text = "\n".join(lines)
        orgs = ner_engine.extract_organizations(full_text)
        for org in orgs:
            org_lower = org.lower()
            if any(kw in org_lower for kw in institution_keywords):
                return org

        # Return first ORG entity if no institution keyword found
        if orgs:
            return orgs[0]

        return None

    def _clean_institution(self, text: str) -> str:
        """Clean institution name."""
        # Remove location info after comma
        text = re.sub(r",.*$", "", text)
        # Remove dates
        text = patterns.YEAR.sub("", text)
        return text.strip()

    # ─── GPA Extraction ────────────────────────────────────────────────────────
    def _extract_gpa(self, text: str) -> Optional[str]:
        """Extract GPA or grade information."""
        match = patterns.GPA.search(text)
        if match:
            gpa   = match.group(1)
            scale = match.group(2)
            if scale:
                return f"{gpa}/{scale}"
            return gpa
        return None

    # ─── Sorting ───────────────────────────────────────────────────────────────
    def _sort_by_rank(self, education: list[dict]) -> list[dict]:
        """Sort education entries by degree rank (highest first)."""
        def rank_key(edu):
            degree = (edu.get("degree") or "").lower()
            for key, rank in DEGREE_RANK.items():
                if key in degree:
                    return -rank  # Negative for descending sort
            return 0

        return sorted(education, key=rank_key)

    def get_highest_degree(self, education: list[dict]) -> Optional[str]:
        """Return the highest degree from a list of education entries."""
        sorted_edu = self._sort_by_rank(education)
        if sorted_edu:
            return sorted_edu[0].get("degree")
        return None


# ─── Singleton ─────────────────────────────────────────────────────────────────
education_extractor = EducationExtractor()
