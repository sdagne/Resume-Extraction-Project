# app/extraction/experience_extractor.py

import re
from typing import Optional

from app.utils.logger import get_logger
from app.utils import regex_patterns as patterns
from app.nlp.text_cleaner import text_cleaner
from app.nlp.ner_engine   import ner_engine
from app.nlp.date_parser  import date_parser

logger = get_logger(__name__)

# ─── Common Job Title Words ────────────────────────────────────────────────────
JOB_TITLE_INDICATORS = [
    "engineer", "developer", "manager", "director", "analyst",
    "designer", "architect", "consultant", "specialist", "lead",
    "senior", "junior", "intern", "officer", "executive",
    "coordinator", "administrator", "scientist", "researcher",
    "head", "chief", "vp", "president", "associate", "staff",
    "principal", "product", "project", "program", "technical",
    "software", "data", "cloud", "devops", "fullstack", "backend",
    "frontend", "mobile", "security", "qa", "test", "scrum",
]

# ─── Company Suffixes ──────────────────────────────────────────────────────────
COMPANY_SUFFIXES = [
    r"\bInc\.?\b", r"\bLtd\.?\b", r"\bLLC\b", r"\bCorp\.?\b",
    r"\bCo\.?\b",  r"\bGmbH\b",   r"\bAG\b",  r"\bSA\b",
    r"\bPLC\b",    r"\bGroup\b",  r"\bHoldings\b",
]
COMPANY_SUFFIX_PATTERN = re.compile(
    "|".join(COMPANY_SUFFIXES), re.IGNORECASE
)


class ExperienceExtractor:
    """
    Extracts work experience entries from resume text.

    Each entry contains:
      - Job title
      - Company name
      - Location
      - Start date / End date
      - Duration (calculated)
      - Is current position
      - Description / responsibilities

    Strategy:
      1. Split section into individual job entries
         (using date patterns as natural boundaries)
      2. For each entry, extract fields using NER + regex + heuristics
      3. Calculate duration and total experience
    """

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def extract(self, section_text: str) -> list[dict]:
        """
        Extract all work experience entries from section text.

        Returns:
            List of experience dicts, most recent first.
        """
        if not section_text or not section_text.strip():
            return []

        # Clean text
        cleaned = text_cleaner.clean(section_text)

        # Split into individual job entries
        entries = self._split_into_entries(cleaned)

        experiences = []
        for entry_text in entries:
            if not entry_text.strip():
                continue

            exp = self._parse_entry(entry_text)
            if exp and (exp.get("job_title") or exp.get("company")):
                experiences.append(exp)

        # Sort by start date (most recent first)
        experiences = self._sort_by_date(experiences)

        logger.info(f"Extracted {len(experiences)} experience entries")
        return experiences

    # ─── Entry Splitting ───────────────────────────────────────────────────────
    def _split_into_entries(self, text: str) -> list[str]:
        """
        Split the experience section into individual job entries.

        Strategy:
          - Date ranges act as natural entry boundaries
          - Job title patterns also signal new entries
          - Blank lines between entries
        """
        lines  = text.splitlines()
        entries = []
        current = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                # Blank line might signal new entry
                if current:
                    # Check if next non-empty line looks like a new entry
                    next_lines = [
                        l.strip() for l in lines[i+1:i+4]
                        if l.strip()
                    ]
                    if next_lines and self._is_entry_start(next_lines[0]):
                        entries.append("\n".join(current))
                        current = []
                continue

            # Check if this line starts a new entry
            if current and self._is_entry_start(stripped):
                # Save previous entry
                entries.append("\n".join(current))
                current = [stripped]
            else:
                current.append(stripped)

        # Don't forget the last entry
        if current:
            entries.append("\n".join(current))

        # If no splitting happened, treat whole text as one entry
        if not entries:
            entries = [text]

        return entries

    def _is_entry_start(self, line: str) -> bool:
        """
        Determine if a line signals the start of a new job entry.
        Signals: date range, job title pattern, company name pattern.
        """
        # Has a date range
        if patterns.DATE_RANGE.search(line):
            return True

        # Has a year
        if patterns.YEAR.search(line):
            return True

        # Looks like a job title
        line_lower = line.lower()
        if any(indicator in line_lower for indicator in JOB_TITLE_INDICATORS[:10]):
            if len(line.split()) <= 8:
                return True

        return False

    # ─── Entry Parsing ─────────────────────────────────────────────────────────
    def _parse_entry(self, entry_text: str) -> dict:
        """
        Parse a single job entry block into structured fields.
        """
        lines = [l.strip() for l in entry_text.splitlines() if l.strip()]
        if not lines:
            return {}

        result = {
            "job_title":       None,
            "company":         None,
            "location":        None,
            "start_date":      None,
            "end_date":        None,
            "duration_years":  None,
            "is_current":      False,
            "description":     None,
            "responsibilities": [],
        }

        # ── Step 1: Extract date range ─────────────────────────────────────────
        date_info, date_line_idx = self._extract_date_from_lines(lines)
        if date_info:
            result["start_date"]     = date_info.get("start_date")
            result["end_date"]       = date_info.get("end_date")
            result["is_current"]     = date_info.get("is_current", False)
            result["duration_years"] = date_info.get("duration_years")

        # ── Step 2: Extract job title and company ──────────────────────────────
        title_company = self._extract_title_company(
            lines, skip_idx=date_line_idx
        )
        result["job_title"] = title_company.get("job_title")
        result["company"]   = title_company.get("company")
        result["location"]  = title_company.get("location")

        # ── Step 3: Extract description and responsibilities ───────────────────
        desc_info = self._extract_description(
            lines,
            skip_indices={date_line_idx} if date_line_idx is not None else set(),
            title=result["job_title"],
            company=result["company"],
        )
        result["description"]      = desc_info.get("description")
        result["responsibilities"] = desc_info.get("responsibilities", [])

        return result

    # ─── Date Extraction ───────────────────────────────────────────────────────
    def _extract_date_from_lines(
        self,
        lines: list[str],
    ) -> tuple[Optional[dict], Optional[int]]:
        """
        Find and parse the date range from entry lines.
        Returns (date_info_dict, line_index).
        """
        for i, line in enumerate(lines):
            if patterns.DATE_RANGE.search(line):
                date_info = date_parser.parse_date_range(line)
                if date_info.get("start_date") or date_info.get("end_date"):
                    return date_info, i

        # Try year-only ranges
        for i, line in enumerate(lines):
            year_matches = patterns.YEAR.findall(line)
            if len(year_matches) >= 2:
                start_year = year_matches[0]
                end_year   = year_matches[-1]
                date_info  = date_parser.parse_date_range(
                    f"{start_year} - {end_year}"
                )
                return date_info, i
            elif len(year_matches) == 1 and "present" in line.lower():
                date_info = date_parser.parse_date_range(
                    f"{year_matches[0]} - Present"
                )
                return date_info, i

        return None, None

    # ─── Title / Company Extraction ────────────────────────────────────────────
    def _extract_title_company(
        self,
        lines: list[str],
        skip_idx: Optional[int] = None,
    ) -> dict:
        """
        Extract job title, company name, and location from entry lines.

        Handles common formats:
          - "Software Engineer | Google | New York"
          - "Software Engineer @ Google"
          - "Software Engineer\nGoogle"
          - "Google - Software Engineer"
        """
        result = {"job_title": None, "company": None, "location": None}

        # Filter out the date line and description lines
        candidate_lines = [
            (i, line) for i, line in enumerate(lines)
            if i != skip_idx
            and len(line.split()) <= 12
            and not patterns.DATE_RANGE.search(line)
            and not patterns.BULLET_POINT.match(line)
        ]

        if not candidate_lines:
            return result

        # ── Try separator-based parsing first ─────────────────────────────────
        for _, line in candidate_lines[:3]:
            parsed = self._parse_title_company_separator(line)
            if parsed.get("job_title") and parsed.get("company"):
                return parsed
            if parsed.get("job_title") or parsed.get("company"):
                result.update({k: v for k, v in parsed.items() if v})

        # ── Fallback: Line-by-line analysis ───────────────────────────────────
        if not result["job_title"] and not result["company"]:
            for _, line in candidate_lines[:4]:
                if self._looks_like_job_title(line) and not result["job_title"]:
                    result["job_title"] = self._clean_title(line)
                elif self._looks_like_company(line) and not result["company"]:
                    result["company"] = self._clean_company(line)

        # ── NER fallback ──────────────────────────────────────────────────────
        if not result["company"]:
            header_text = "\n".join(
                line for _, line in candidate_lines[:3]
            )
            orgs = ner_engine.extract_organizations(header_text)
            if orgs:
                result["company"] = orgs[0]

        # ── Location extraction ────────────────────────────────────────────────
        if not result["location"]:
            header_text = "\n".join(
                line for _, line in candidate_lines[:3]
            )
            locs = ner_engine.extract_locations(header_text)
            if locs:
                result["location"] = locs[0]

        return result

    def _parse_title_company_separator(self, line: str) -> dict:
        """
        Parse "Job Title | Company | Location" or
        "Job Title @ Company" or "Job Title, Company" formats.
        """
        result = {"job_title": None, "company": None, "location": None}

        # Separator patterns: |, @, —, –, ·, •
        sep_pattern = re.compile(r"\s*[|@—–·•]\s*")
        parts = sep_pattern.split(line)

        if len(parts) >= 2:
            result["job_title"] = self._clean_title(parts[0])
            result["company"]   = self._clean_company(parts[1])
            if len(parts) >= 3:
                result["location"] = parts[2].strip()
            return result

        # Comma separation: "Job Title, Company Name"
        comma_parts = line.split(",", 1)
        if len(comma_parts) == 2:
            if self._looks_like_job_title(comma_parts[0]):
                result["job_title"] = self._clean_title(comma_parts[0])
                result["company"]   = self._clean_company(comma_parts[1])
                return result

        # "at" keyword: "Software Engineer at Google"
        at_match = re.match(
            r"^(.+?)\s+at\s+(.+)$", line, re.IGNORECASE
        )
        if at_match:
            result["job_title"] = self._clean_title(at_match.group(1))
            result["company"]   = self._clean_company(at_match.group(2))
            return result

        return result

    # ─── Description Extraction ────────────────────────────────────────────────
    def _extract_description(
        self,
        lines: list[str],
        skip_indices: set,
        title: Optional[str],
        company: Optional[str],
    ) -> dict:
        """
        Extract job description and bullet-point responsibilities.
        """
        description_lines  = []
        responsibilities   = []

        # Title/company text to skip
        skip_texts = set()
        if title:
            skip_texts.add(title.lower().strip())
        if company:
            skip_texts.add(company.lower().strip())

        for i, line in enumerate(lines):
            if i in skip_indices:
                continue

            stripped = line.strip()
            if not stripped:
                continue

            # Skip if it's the title or company line
            if stripped.lower() in skip_texts:
                continue

            # Skip date lines
            if patterns.DATE_RANGE.search(stripped):
                continue

            # Check if it's a bullet point responsibility
            if patterns.BULLET_POINT.match(stripped):
                clean = patterns.BULLET_POINT.sub("", stripped).strip()
                if clean:
                    responsibilities.append(clean)
            elif len(stripped.split()) > 5:
                # Long line → part of description
                description_lines.append(stripped)

        description = " ".join(description_lines) if description_lines else None

        return {
            "description":      description,
            "responsibilities": responsibilities,
        }

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _looks_like_job_title(self, text: str) -> bool:
        """Heuristic: does this text look like a job title?"""
        text_lower = text.lower().strip()
        word_count = len(text.split())

        if word_count > 8:
            return False

        return any(
            indicator in text_lower
            for indicator in JOB_TITLE_INDICATORS
        )

    def _looks_like_company(self, text: str) -> bool:
        """Heuristic: does this text look like a company name?"""
        if COMPANY_SUFFIX_PATTERN.search(text):
            return True

        # Capitalized words (proper noun pattern)
        words = text.split()
        if 1 <= len(words) <= 5:
            if sum(1 for w in words if w and w[0].isupper()) >= len(words) * 0.6:
                return True

        return False

    def _clean_title(self, title: str) -> Optional[str]:
        """Clean and normalize a job title."""
        if not title:
            return None
        title = re.sub(r"\s+", " ", title).strip()
        title = re.sub(r"[:\-|@]+$", "", title).strip()
        return title if title else None

    def _clean_company(self, company: str) -> Optional[str]:
        """Clean and normalize a company name."""
        if not company:
            return None
        company = re.sub(r"\s+", " ", company).strip()
        company = re.sub(r"[:\-|@]+$", "", company).strip()
        return company if company else None

    def _sort_by_date(self, experiences: list[dict]) -> list[dict]:
        """Sort experiences by start date, most recent first."""
        def sort_key(exp):
            start = exp.get("start_date")
            if not start:
                return (0, 0)
            dt = date_parser.parse_date_string(start)
            if dt:
                return (dt.year, dt.month)
            return (0, 0)

        return sorted(experiences, key=sort_key, reverse=True)


# ─── Singleton ─────────────────────────────────────────────────────────────────
experience_extractor = ExperienceExtractor()
