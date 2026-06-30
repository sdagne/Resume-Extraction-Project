# app/matching/job_title_normalizer.py

import re
import json
from typing import Optional

from rapidfuzz import process, fuzz

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class JobTitleNormalizer:
    """
    Normalizes job titles to standard forms.

    Handles:
      - Seniority level extraction (Senior, Junior, Lead, etc.)
      - Role normalization (SWE → Software Engineer)
      - Abbreviation expansion
      - Title cleaning (remove company-specific prefixes)
    """

    # ─── Seniority Levels ──────────────────────────────────────────────────────
    SENIORITY_MAP = {
        # Junior
        "junior":       "Junior",
        "jr":           "Junior",
        "jr.":          "Junior",
        "entry level":  "Junior",
        "entry-level":  "Junior",
        "associate":    "Associate",
        "trainee":      "Trainee",
        "intern":       "Intern",
        "graduate":     "Graduate",

        # Mid
        "mid level":    "Mid-Level",
        "mid-level":    "Mid-Level",
        "intermediate": "Mid-Level",

        # Senior
        "senior":       "Senior",
        "sr":           "Senior",
        "sr.":          "Senior",
        "experienced":  "Senior",

        # Lead / Principal
        "lead":         "Lead",
        "tech lead":    "Tech Lead",
        "principal":    "Principal",
        "staff":        "Staff",

        # Management
        "manager":      "Manager",
        "head":         "Head",
        "director":     "Director",
        "vp":           "VP",
        "vice president": "VP",
        "chief":        "Chief",
        "c-level":      "C-Level",
        "cto":          "CTO",
        "ceo":          "CEO",
        "coo":          "COO",
        "cfo":          "CFO",
        "ciso":         "CISO",
    }

    # ─── Role Abbreviations ────────────────────────────────────────────────────
    ROLE_ABBREVIATIONS = {
        "swe":          "Software Engineer",
        "sde":          "Software Development Engineer",
        "sre":          "Site Reliability Engineer",
        "devops":       "DevOps Engineer",
        "qa":           "Quality Assurance Engineer",
        "qae":          "Quality Assurance Engineer",
        "ba":           "Business Analyst",
        "sa":           "Solutions Architect",
        "pm":           "Product Manager",
        "po":           "Product Owner",
        "ux":           "UX Designer",
        "ui":           "UI Designer",
        "ux/ui":        "UX/UI Designer",
        "ui/ux":        "UI/UX Designer",
        "ml":           "Machine Learning Engineer",
        "ds":           "Data Scientist",
        "da":           "Data Analyst",
        "de":           "Data Engineer",
        "dba":          "Database Administrator",
        "ios":          "iOS Developer",
        "fe":           "Frontend Developer",
        "be":           "Backend Developer",
        "fs":           "Full Stack Developer",
        "fullstack":    "Full Stack Developer",
        "full stack":   "Full Stack Developer",
        "frontend":     "Frontend Developer",
        "backend":      "Backend Developer",
    }

    # ─── Standard Role Titles ──────────────────────────────────────────────────
    STANDARD_TITLES = [
        "Software Engineer", "Software Developer", "Full Stack Developer",
        "Frontend Developer", "Backend Developer", "Mobile Developer",
        "iOS Developer", "Android Developer",
        "DevOps Engineer", "Site Reliability Engineer", "Platform Engineer",
        "Cloud Engineer", "Infrastructure Engineer",
        "Data Scientist", "Data Analyst", "Data Engineer",
        "Machine Learning Engineer", "AI Engineer", "NLP Engineer",
        "Business Analyst", "Systems Analyst", "Product Analyst",
        "Product Manager", "Product Owner", "Program Manager",
        "Project Manager", "Scrum Master", "Agile Coach",
        "UX Designer", "UI Designer", "UX/UI Designer",
        "QA Engineer", "Test Engineer", "Automation Engineer",
        "Security Engineer", "Cybersecurity Analyst", "Penetration Tester",
        "Database Administrator", "Systems Administrator",
        "Network Engineer", "Solutions Architect", "Cloud Architect",
        "Technical Lead", "Engineering Manager", "CTO",
        "Software Architect", "Enterprise Architect",
    ]

    def __init__(self):
        self._title_lookup: dict[str, str] = {}
        self._build_lookup()

    def _build_lookup(self) -> None:
        """Build normalized title lookup dict."""
        # Standard titles
        for title in self.STANDARD_TITLES:
            key = self._normalize_key(title)
            self._title_lookup[key] = title

        # Abbreviations
        for abbr, full in self.ROLE_ABBREVIATIONS.items():
            key = self._normalize_key(abbr)
            self._title_lookup[key] = full

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def normalize(self, title: str) -> dict:
        """
        Normalize a job title.

        Returns:
            {
                "original":   str,
                "normalized": str,
                "seniority":  str | None,
                "role":       str,
                "confidence": float,
            }
        """
        if not title or not title.strip():
            return self._empty_result(title or "")

        original = title.strip()

        # ── Step 1: Extract seniority ──────────────────────────────────────────
        seniority, title_without_seniority = self._extract_seniority(original)

        # ── Step 2: Normalize role ─────────────────────────────────────────────
        role, confidence = self._normalize_role(title_without_seniority)

        # ── Step 3: Build normalized title ────────────────────────────────────
        if seniority and role:
            normalized = f"{seniority} {role}"
        elif role:
            normalized = role
        else:
            normalized = original

        return {
            "original":   original,
            "normalized": normalized,
            "seniority":  seniority,
            "role":       role or original,
            "confidence": confidence,
        }

    def normalize_title_only(self, title: str) -> str:
        """Quick method — returns just the normalized title string."""
        return self.normalize(title)["normalized"]

    # ─── Seniority Extraction ──────────────────────────────────────────────────
    def _extract_seniority(
        self,
        title: str,
    ) -> tuple[Optional[str], str]:
        """
        Extract seniority level from title.

        Returns:
            (seniority_label, title_without_seniority)
        """
        title_lower = title.lower().strip()

        # Check multi-word seniority first
        for key in sorted(self.SENIORITY_MAP.keys(), key=len, reverse=True):
            if key in title_lower:
                seniority = self.SENIORITY_MAP[key]
                # Remove seniority from title
                cleaned = re.sub(
                    re.escape(key), "", title_lower,
                    flags=re.IGNORECASE,
                ).strip()
                cleaned = re.sub(r"\s+", " ", cleaned).strip(" -,")
                return seniority, cleaned.title() if cleaned else title

        return None, title

    # ─── Role Normalization ────────────────────────────────────────────────────
    def _normalize_role(
        self,
        title: str,
    ) -> tuple[Optional[str], float]:
        """
        Normalize role part of title.

        Returns:
            (normalized_role, confidence)
        """
        if not title:
            return None, 0.0

        # ── Exact / normalized match ───────────────────────────────────────────
        key = self._normalize_key(title)
        if key in self._title_lookup:
            return self._title_lookup[key], 1.0

        # ── Abbreviation match ────────────────────────────────────────────────
        title_lower = title.lower().strip()
        if title_lower in self.ROLE_ABBREVIATIONS:
            return self.ROLE_ABBREVIATIONS[title_lower], 0.95

        # ── Fuzzy match against standard titles ───────────────────────────────
        result = process.extractOne(
            title,
            self.STANDARD_TITLES,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=70,
        )
        if result:
            matched, score, _ = result
            return matched, round(score / 100, 2)

        # ── Partial keyword match ──────────────────────────────────────────────
        partial = self._partial_match(title)
        if partial:
            return partial, 0.65

        # ── Return cleaned original ────────────────────────────────────────────
        return title.title(), 0.50

    def _partial_match(self, title: str) -> Optional[str]:
        """
        Match based on key role keywords in the title.
        """
        title_lower = title.lower()

        keyword_map = {
            "software engineer":   ["software", "engineer", "swe", "sde"],
            "data scientist":      ["data scientist", "data science"],
            "data engineer":       ["data engineer", "data pipeline", "etl"],
            "data analyst":        ["data analyst", "business intelligence"],
            "machine learning":    ["machine learning", "ml engineer", "ai engineer"],
            "devops engineer":     ["devops", "devsecops", "platform engineer"],
            "frontend developer":  ["frontend", "front-end", "react developer", "ui developer"],
            "backend developer":   ["backend", "back-end", "api developer"],
            "full stack developer":["full stack", "fullstack"],
            "mobile developer":    ["mobile", "ios developer", "android developer"],
            "product manager":     ["product manager", "product owner"],
            "ux designer":         ["ux", "user experience", "ui/ux"],
            "qa engineer":         ["qa", "quality assurance", "test engineer"],
            "security engineer":   ["security", "cybersecurity", "infosec"],
            "cloud engineer":      ["cloud engineer", "cloud architect"],
            "database administrator": ["dba", "database admin"],
        }

        for standard, keywords in keyword_map.items():
            if any(kw in title_lower for kw in keywords):
                return standard.title()

        return None

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _normalize_key(self, text: str) -> str:
        """Create normalized lookup key."""
        key = text.lower()
        key = re.sub(r"[^\w\s]", " ", key)
        key = re.sub(r"\s+", " ", key).strip()
        return key

    def _empty_result(self, original: str) -> dict:
        return {
            "original":   original,
            "normalized": original,
            "seniority":  None,
            "role":       original,
            "confidence": 0.0,
        }

    def extract_seniority_only(self, title: str) -> Optional[str]:
        """Quick method — returns just the seniority level."""
        seniority, _ = self._extract_seniority(title)
        return seniority

    def get_career_level(self, title: str) -> str:
        """
        Map title to a simplified career level:
        intern → junior → mid → senior → lead → manager → executive
        """
        seniority = (self.extract_seniority_only(title) or "").lower()

        level_map = {
            "intern":     "intern",
            "trainee":    "intern",
            "graduate":   "junior",
            "junior":     "junior",
            "associate":  "junior",
            "mid-level":  "mid",
            "senior":     "senior",
            "lead":       "lead",
            "tech lead":  "lead",
            "principal":  "lead",
            "staff":      "lead",
            "manager":    "manager",
            "head":       "manager",
            "director":   "manager",
            "vp":         "executive",
            "cto":        "executive",
            "ceo":        "executive",
            "chief":      "executive",
        }

        return level_map.get(seniority, "mid")


# ─── Singleton ─────────────────────────────────────────────────────────────────
job_title_normalizer = JobTitleNormalizer()
