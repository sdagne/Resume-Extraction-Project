# Project names, descriptions, tech stack
# app/extraction/projects_extractor.py

import re
from typing import Optional

from app.utils.logger import get_logger
from app.nlp.text_cleaner import text_cleaner
from app.nlp.date_parser  import date_parser
from app.utils import regex_patterns as patterns
from app.extraction.skills_extractor import ALL_KNOWN_SKILLS

logger = get_logger(__name__)


class ProjectsExtractor:
    """
    Extracts project entries from resume text.

    Each entry contains:
      - Project name
      - Description
      - Technologies used
      - Project URL (if present)
      - Start/End dates
    """

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def extract(self, section_text: str) -> list[dict]:
        """
        Extract all project entries from section text.

        Returns:
            List of project dicts.
        """
        if not section_text or not section_text.strip():
            return []

        cleaned = text_cleaner.clean(section_text)
        entries = self._split_into_entries(cleaned)

        projects = []
        for entry_text in entries:
            if not entry_text.strip():
                continue
            project = self._parse_entry(entry_text)
            if project and project.get("name"):
                projects.append(project)

        logger.info(f"Extracted {len(projects)} projects")
        return projects

    # ─── Entry Splitting ───────────────────────────────────────────────────────
    def _split_into_entries(self, text: str) -> list[str]:
        """Split projects section into individual project entries."""
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
                    if next_lines and self._is_project_start(next_lines[0]):
                        entries.append("\n".join(current))
                        current = []
                continue

            if current and self._is_project_start(stripped):
                entries.append("\n".join(current))
                current = [stripped]
            else:
                current.append(stripped)

        if current:
            entries.append("\n".join(current))

        return entries if entries else [text]

    def _is_project_start(self, line: str) -> bool:
        """Check if a line starts a new project entry."""
        # Short line that looks like a project name
        if len(line.split()) <= 6 and not patterns.BULLET_POINT.match(line):
            if not patterns.DATE_RANGE.search(line):
                return True
        return False

    # ─── Entry Parsing ─────────────────────────────────────────────────────────
    def _parse_entry(self, entry_text: str) -> dict:
        """Parse a single project entry."""
        lines = [l.strip() for l in entry_text.splitlines() if l.strip()]
        if not lines:
            return {}

        result = {
            "name":         None,
            "description":  None,
            "technologies": [],
            "url":          None,
            "start_date":   None,
            "end_date":     None,
        }

        # ── Project name: usually the first line ───────────────────────────────
        first_line = lines[0]
        if not patterns.BULLET_POINT.match(first_line):
            result["name"] = self._clean_project_name(first_line)

        # ── URL ────────────────────────────────────────────────────────────────
        result["url"] = self._extract_url(entry_text)

        # ── Dates ──────────────────────────────────────────────────────────────
        date_info = self._extract_dates(lines)
        result["start_date"] = date_info.get("start_date")
        result["end_date"]   = date_info.get("end_date")

        # ── Technologies ───────────────────────────────────────────────────────
        result["technologies"] = self._extract_technologies(entry_text)

        # ── Description ────────────────────────────────────────────────────────
        result["description"] = self._extract_description(
            lines, skip_first=True
        )

        return result

    # ─── Field Extractors ──────────────────────────────────────────────────────
    def _clean_project_name(self, name: str) -> str:
        """Clean project name."""
        name = re.sub(r"^[\d\.\-\)]+\s*", "", name)  # Remove numbering
        name = re.sub(r"\s*[-|–]\s*.*$", "", name)    # Remove trailing info
        return name.strip()

    def _extract_url(self, text: str) -> Optional[str]:
        """Extract project URL."""
        url_pattern = re.compile(
            r"https?://[^\s,;)>\"']+|github\.com/[^\s,;)>\"']+",
            re.IGNORECASE,
        )
        match = url_pattern.search(text)
        if match:
            url = match.group(0)
            if not url.startswith("http"):
                url = "https://" + url
            return url
        return None

    def _extract_dates(self, lines: list[str]) -> dict:
        """Extract project dates."""
        for line in lines:
            if patterns.DATE_RANGE.search(line):
                return date_parser.parse_date_range(line)
        return {"start_date": None, "end_date": None}

    def _extract_technologies(self, text: str) -> list[str]:
        """
        Extract technologies used in the project.
        Matches against known skills taxonomy.
        """
        found = []
        text_lower = text.lower()

        # Tech section pattern: "Technologies: Python, React, ..."
        tech_pattern = re.compile(
            r"(?:tech(?:nolog(?:y|ies))?|tools?|stack|built\s+with|"
            r"using|languages?)[:\s]+([^\n]+)",
            re.IGNORECASE,
        )
        tech_match = tech_pattern.search(text)
        if tech_match:
            tech_str = tech_match.group(1)
            parts    = re.split(r"[,;|]", tech_str)
            found.extend([p.strip() for p in parts if p.strip()])

        # Mine from text using taxonomy
        for skill in ALL_KNOWN_SKILLS:
            pattern = re.compile(
                r"\b" + re.escape(skill) + r"\b",
                re.IGNORECASE,
            )
            if pattern.search(text_lower) and skill not in [f.lower() for f in found]:
                found.append(skill)

        from app.utils.helpers import deduplicate
        return deduplicate([f for f in found if f and len(f) > 1])

    def _extract_description(
        self,
        lines: list[str],
        skip_first: bool = True,
    ) -> Optional[str]:
        """Extract project description from lines."""
        desc_lines = []
        start_idx  = 1 if skip_first else 0

        for line in lines[start_idx:]:
            # Skip date lines and tech lines
            if patterns.DATE_RANGE.search(line):
                continue
            if re.match(r"(?:tech|tools?|stack|url|link)[:\s]", line, re.IGNORECASE):
                continue
            if patterns.BULLET_POINT.match(line):
                clean = patterns.BULLET_POINT.sub("", line).strip()
                if clean:
                    desc_lines.append(clean)
            elif len(line.split()) >= 4:
                desc_lines.append(line)

        if not desc_lines:
            return None

        return " ".join(desc_lines)


# ─── Singleton ─────────────────────────────────────────────────────────────────
projects_extractor = ProjectsExtractor()
