# app/extraction/skills_extractor.py

import re
import json
from pathlib import Path
from typing import Optional

from app.config import settings
from app.utils.logger import get_logger
from app.utils.helpers import deduplicate
from app.utils import regex_patterns as patterns
from app.nlp.text_cleaner import text_cleaner

logger = get_logger(__name__)

# ─── Skill Category Keywords ───────────────────────────────────────────────────
SKILL_CATEGORIES = {
    "programming_languages": [
        "python", "java", "javascript", "typescript", "c++", "c#", "c",
        "ruby", "go", "golang", "rust", "swift", "kotlin", "scala",
        "php", "r", "matlab", "perl", "shell", "bash", "powershell",
        "objective-c", "dart", "elixir", "haskell", "lua", "groovy",
    ],
    "frameworks": [
        "django", "flask", "fastapi", "spring", "spring boot", "hibernate",
        "react", "angular", "vue", "next.js", "nuxt.js", "express",
        "node.js", "nestjs", "laravel", "rails", "asp.net", ".net",
        "tensorflow", "pytorch", "keras", "scikit-learn", "pandas",
        "numpy", "opencv", "hugging face", "langchain",
        "bootstrap", "tailwind", "jquery", "redux",
    ],
    "databases": [
        "mysql", "postgresql", "sqlite", "mongodb", "redis", "cassandra",
        "oracle", "sql server", "mssql", "dynamodb", "firebase",
        "elasticsearch", "neo4j", "couchdb", "mariadb", "influxdb",
        "snowflake", "bigquery", "redshift",
    ],
    "cloud_devops": [
        "aws", "azure", "gcp", "google cloud", "docker", "kubernetes",
        "jenkins", "gitlab ci", "github actions", "terraform", "ansible",
        "puppet", "chef", "nginx", "apache", "linux", "unix",
        "ci/cd", "devops", "helm", "prometheus", "grafana", "elk",
        "cloudformation", "pulumi", "vagrant",
    ],
    "tools": [
        "git", "github", "gitlab", "bitbucket", "jira", "confluence",
        "slack", "trello", "asana", "figma", "sketch", "adobe xd",
        "postman", "swagger", "sonarqube", "selenium", "cypress",
        "jest", "pytest", "junit", "maven", "gradle", "npm", "yarn",
        "webpack", "vite", "intellij", "vscode", "eclipse", "xcode",
    ],
    "soft_skills": [
        "leadership", "communication", "teamwork", "problem solving",
        "critical thinking", "time management", "adaptability",
        "creativity", "collaboration", "project management",
        "agile", "scrum", "kanban", "mentoring", "coaching",
        "presentation", "negotiation", "analytical thinking",
    ],
    "data_science": [
        "machine learning", "deep learning", "nlp", "computer vision",
        "data analysis", "data visualization", "statistics",
        "tableau", "power bi", "looker", "matplotlib", "seaborn",
        "spark", "hadoop", "airflow", "dbt", "etl", "data pipeline",
        "feature engineering", "model deployment", "mlops",
    ],
    "security": [
        "cybersecurity", "penetration testing", "ethical hacking",
        "soc", "siem", "firewall", "vpn", "ssl", "tls",
        "owasp", "iso 27001", "gdpr", "compliance",
    ],
}

# ─── Flatten all skills for quick lookup ──────────────────────────────────────
ALL_KNOWN_SKILLS = {
    skill
    for skills in SKILL_CATEGORIES.values()
    for skill in skills
}


class SkillsExtractor:
    """
    Extracts and categorizes skills from resume text.

    Strategy (layered):
      1. Skills section parsing (bullet points, comma-separated lists)
      2. Taxonomy matching (exact + fuzzy) against known skill lists
      3. Noun phrase extraction for unknown skills
      4. Skill categorization into technical/soft/tools/etc.
    """

    def __init__(self):
        self._external_taxonomy = None

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def extract(
        self,
        section_text: str,
        full_resume_text: Optional[str] = None,
    ) -> dict:
        """
        Extract and categorize all skills.

        Args:
            section_text:      Text from the skills section
            full_resume_text:  Full resume text for additional skill mining

        Returns:
            {
                "all":              list[str],   # All unique skills
                "programming_languages": list[str],
                "frameworks":       list[str],
                "databases":        list[str],
                "cloud_devops":     list[str],
                "tools":            list[str],
                "soft_skills":      list[str],
                "data_science":     list[str],
                "security":         list[str],
                "other":            list[str],
            }
        """
        all_skills = []

        # ── Layer 1: Parse skills section ─────────────────────────────────────
        if section_text:
            section_skills = self._parse_skills_section(section_text)
            all_skills.extend(section_skills)

        # ── Layer 2: Mine skills from full resume text ─────────────────────────
        if full_resume_text:
            mined_skills = self._mine_skills_from_text(full_resume_text)
            all_skills.extend(mined_skills)

        # ── Layer 3: Taxonomy matching + fuzzy matching ────────────────────────
        matched_skills = self._match_against_taxonomy(all_skills)

        # ── Layer 4: Categorize ────────────────────────────────────────────────
        categorized = self._categorize_skills(matched_skills)

        # ── Layer 5: Deduplicate all lists ─────────────────────────────────────
        for key in categorized:
            categorized[key] = deduplicate(
                [s.strip() for s in categorized[key] if s.strip()]
            )

        # Build flat "all" list
        all_flat = deduplicate([
            skill
            for category_skills in categorized.values()
            for skill in category_skills
        ])
        categorized["all"] = all_flat

        logger.info(
            f"Skills extracted: {len(all_flat)} total — "
            + ", ".join(
                f"{k}={len(v)}"
                for k, v in categorized.items()
                if v and k != "all"
            )
        )
        return categorized

    # ─── Skills Section Parser ─────────────────────────────────────────────────
    def _parse_skills_section(self, text: str) -> list[str]:
        """
        Parse skills from a dedicated skills section.
        Handles formats:
          - Comma-separated: "Python, Java, React"
          - Bullet points:   "• Python\n• Java"
          - Categorized:     "Languages: Python, Java\nFrameworks: React"
          - Table format:    "Python | Java | React"
        """
        skills = []
        lines  = text_cleaner.extract_clean_lines(text)

        for line in lines:
            # Skip section headers
            if self._is_category_label(line):
                # Extract skills after the colon
                if ":" in line:
                    after_colon = line.split(":", 1)[1]
                    skills.extend(self._split_skill_list(after_colon))
                continue

            # Bullet point line
            if patterns.BULLET_POINT.match(line):
                clean = patterns.BULLET_POINT.sub("", line).strip()
                skills.extend(self._split_skill_list(clean))
                continue

            # Pipe-separated (table format)
            if "|" in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                skills.extend(parts)
                continue

            # Comma or semicolon separated
            if "," in line or ";" in line:
                skills.extend(self._split_skill_list(line))
                continue

            # Single skill on a line
            if len(line.split()) <= 4:
                skills.append(line.strip())

        return [s for s in skills if s and len(s) > 1]

    def _split_skill_list(self, text: str) -> list[str]:
        """Split a comma/semicolon/pipe separated skill string."""
        # Split on comma, semicolon, pipe, bullet
        parts = re.split(r"[,;|•·]", text)
        cleaned = []
        for part in parts:
            part = part.strip().strip("•·-").strip()
            if part and len(part) > 1:
                cleaned.append(part)
        return cleaned

    def _is_category_label(self, line: str) -> bool:
        """
        Check if a line is a skill category label
        like "Programming Languages:" or "Tools & Technologies:".
        """
        category_keywords = [
            "language", "framework", "tool", "technology", "platform",
            "database", "software", "skill", "competenc", "expertise",
            "technical", "professional", "soft skill",
        ]
        line_lower = line.lower().rstrip(":")
        return (
            any(kw in line_lower for kw in category_keywords)
            and len(line.split()) <= 5
        )

    # ─── Taxonomy Mining ───────────────────────────────────────────────────────
    def _mine_skills_from_text(self, text: str) -> list[str]:
        """
        Mine skills from full resume text by matching against
        the known skills taxonomy.
        """
        found  = []
        text_lower = text.lower()

        for skill in ALL_KNOWN_SKILLS:
            # Use word boundary matching for accuracy
            pattern = re.compile(
                r"\b" + re.escape(skill) + r"\b",
                re.IGNORECASE,
            )
            if pattern.search(text_lower):
                found.append(skill)

        return found

    # ─── Taxonomy Matching ─────────────────────────────────────────────────────
    def _match_against_taxonomy(self, skills: list[str]) -> list[str]:
        """
        Match extracted skills against the taxonomy using:
          1. Exact match (case-insensitive)
          2. Fuzzy match for near-matches
        """
        from rapidfuzz import process, fuzz

        matched  = []
        taxonomy = list(ALL_KNOWN_SKILLS)

        for skill in skills:
            skill_lower = skill.lower().strip()

            # Exact match
            if skill_lower in ALL_KNOWN_SKILLS:
                matched.append(skill_lower)
                continue

            # Fuzzy match (only for skills >= 4 chars)
            if len(skill_lower) >= 4:
                result = process.extractOne(
                    skill_lower,
                    taxonomy,
                    scorer=fuzz.ratio,
                    score_cutoff=settings.SKILLS_FUZZY_THRESHOLD,
                )
                if result:
                    matched.append(result[0])
                else:
                    # Keep original if it looks like a valid skill
                    if self._is_valid_skill(skill):
                        matched.append(skill.strip())
            else:
                # Short skills (2-3 chars): exact match only
                if skill_lower in ALL_KNOWN_SKILLS:
                    matched.append(skill_lower)

        return deduplicate(matched)

    def _is_valid_skill(self, skill: str) -> bool:
        """
        Validate if a string is likely a real skill.
        Filters out noise, single letters, and common words.
        """
        skill = skill.strip()

        # Too short or too long
        if len(skill) < 2 or len(skill) > 50:
            return False

        # Only digits
        if skill.isdigit():
            return False

        # Common words that aren't skills
        stop_words = {
            "the", "and", "for", "with", "from", "this",
            "that", "have", "been", "will", "are", "was",
            "experience", "knowledge", "understanding", "ability",
            "proficient", "familiar", "working",
        }
        if skill.lower() in stop_words:
            return False

        # Must contain at least one letter
        if not any(c.isalpha() for c in skill):
            return False

        return True

    # ─── Categorization ────────────────────────────────────────────────────────
    def _categorize_skills(self, skills: list[str]) -> dict:
        """
        Categorize skills into predefined categories.
        A skill can only belong to one category (priority order).
        """
        categorized = {cat: [] for cat in SKILL_CATEGORIES}
        categorized["other"] = []

        for skill in skills:
            skill_lower = skill.lower().strip()
            assigned    = False

            for category, category_skills in SKILL_CATEGORIES.items():
                if skill_lower in category_skills:
                    categorized[category].append(skill)
                    assigned = True
                    break

            if not assigned:
                categorized["other"].append(skill)

        return categorized

    # ─── External Taxonomy ─────────────────────────────────────────────────────
    def load_external_taxonomy(self) -> list[str]:
        """
        Load additional skills from the ESCO taxonomy JSON file.
        Falls back to built-in taxonomy if file not found.
        """
        if self._external_taxonomy is not None:
            return self._external_taxonomy

        taxonomy_path = settings.TAXONOMY_DIR / "skills_esco.json"
        try:
            with open(taxonomy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                skills = data if isinstance(data, list) else data.get("skills", [])
                self._external_taxonomy = [
                    s.lower().strip() for s in skills if isinstance(s, str)
                ]
                logger.info(
                    f"Loaded {len(self._external_taxonomy)} "
                    f"skills from ESCO taxonomy"
                )
                return self._external_taxonomy
        except FileNotFoundError:
            logger.warning(
                f"ESCO taxonomy not found at {taxonomy_path}. "
                f"Using built-in taxonomy only."
            )
            self._external_taxonomy = []
            return []
        except Exception as e:
            logger.error(f"Failed to load ESCO taxonomy: {e}")
            self._external_taxonomy = []
            return []


# ─── Singleton ─────────────────────────────────────────────────────────────────
skills_extractor = SkillsExtractor()
