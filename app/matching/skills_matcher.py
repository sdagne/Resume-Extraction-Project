# app/matching/skills_matcher.py

import json
import re
from pathlib import Path
from typing import Optional

from rapidfuzz import process, fuzz

from app.config import settings
from app.utils.logger import get_logger
from app.utils.helpers import deduplicate

logger = get_logger(__name__)


class SkillsMatcher:
    """
    Matches raw extracted skills against a curated taxonomy using:
      1. Exact match          (case-insensitive)
      2. Normalized match     (remove punctuation/spaces)
      3. Fuzzy match          (RapidFuzz token_sort_ratio)
      4. Alias match          (common abbreviations/synonyms)
      5. Substring match      (for compound skill names)

    Also provides:
      - Skill normalization   (js → JavaScript)
      - Skill deduplication   (remove near-duplicates)
      - Skill grouping        (group related skills)
    """

    # ─── Built-in Alias Map ────────────────────────────────────────────────────
    ALIAS_MAP = {
        # Programming Languages
        "js":           "javascript",
        "ts":           "typescript",
        "py":           "python",
        "rb":           "ruby",
        "cpp":          "c++",
        "csharp":       "c#",
        "golang":       "go",
        "objective c":  "objective-c",

        # Frameworks
        "reactjs":      "react",
        "react.js":     "react",
        "vuejs":        "vue",
        "vue.js":       "vue",
        "angularjs":    "angular",
        "nodejs":       "node.js",
        "node":         "node.js",
        "nextjs":       "next.js",
        "nuxtjs":       "nuxt.js",
        "expressjs":    "express",
        "fastapi":      "fastapi",
        "springboot":   "spring boot",
        "asp.net core": "asp.net",
        "dotnet":       ".net",
        ".net core":    ".net",
        "sklearn":      "scikit-learn",
        "scikit learn": "scikit-learn",
        "tf":           "tensorflow",
        "hf":           "hugging face",

        # Cloud
        "amazon web services": "aws",
        "google cloud platform": "gcp",
        "microsoft azure": "azure",
        "gke":          "kubernetes",
        "k8s":          "kubernetes",
        "kube":         "kubernetes",
        "eks":          "aws",
        "aks":          "azure",

        # Databases
        "postgres":     "postgresql",
        "pg":           "postgresql",
        "mongo":        "mongodb",
        "mssql":        "sql server",
        "ms sql":       "sql server",
        "elastic":      "elasticsearch",
        "es":           "elasticsearch",

        # Tools
        "gh":           "github",
        "gl":           "gitlab",
        "bb":           "bitbucket",
        "vsc":          "vscode",
        "vs code":      "vscode",

        # Data
        "ml":           "machine learning",
        "dl":           "deep learning",
        "ai":           "artificial intelligence",
        "cv":           "computer vision",
        "nlp":          "nlp",
        "bi":           "power bi",
        "powerbi":      "power bi",

        # Methodologies
        "agile/scrum":  "agile",
        "scrum master": "scrum",
        "ci cd":        "ci/cd",
        "cicd":         "ci/cd",
    }

    def __init__(self):
        self._taxonomy:          list[str] = []
        self._taxonomy_set:      set[str]  = set()
        self._normalized_lookup: dict[str, str] = {}
        self._loaded             = False

    # ─── Initialization ────────────────────────────────────────────────────────
    def _ensure_loaded(self) -> None:
        """Lazy-load taxonomy on first use."""
        if self._loaded:
            return

        self._taxonomy = self._load_taxonomy()
        self._taxonomy_set = set(self._taxonomy)

        # Build normalized lookup: normalized_key → original_skill
        for skill in self._taxonomy:
            key = self._normalize_key(skill)
            self._normalized_lookup[key] = skill

        # Add aliases to normalized lookup
        for alias, canonical in self.ALIAS_MAP.items():
            key = self._normalize_key(alias)
            self._normalized_lookup[key] = canonical

        self._loaded = True
        logger.info(
            f"SkillsMatcher loaded: {len(self._taxonomy)} skills, "
            f"{len(self._normalized_lookup)} normalized keys"
        )

    def _load_taxonomy(self) -> list[str]:
        """
        Load skills taxonomy from:
          1. ESCO JSON file (if available)
          2. Built-in skill list (fallback)
        """
        from app.extraction.skills_extractor import ALL_KNOWN_SKILLS

        skills = list(ALL_KNOWN_SKILLS)

        # Try loading ESCO taxonomy
        esco_path = settings.TAXONOMY_DIR / "skills_esco.json"
        try:
            with open(esco_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                esco_skills = (
                    data if isinstance(data, list)
                    else data.get("skills", [])
                )
                skills.extend([
                    s.lower().strip()
                    for s in esco_skills
                    if isinstance(s, str)
                ])
                logger.info(f"Loaded {len(esco_skills)} ESCO skills")
        except FileNotFoundError:
            logger.debug("ESCO taxonomy not found, using built-in only")
        except Exception as e:
            logger.warning(f"Failed to load ESCO taxonomy: {e}")

        return deduplicate([s.lower().strip() for s in skills if s])

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def match(
        self,
        skills: list[str],
        threshold: Optional[int] = None,
    ) -> list[dict]:
        """
        Match a list of raw skills against the taxonomy.

        Args:
            skills:    List of raw skill strings to match
            threshold: Fuzzy match threshold (0–100). Uses settings default if None.

        Returns:
            List of match results:
            [
                {
                    "original":   str,   # Input skill
                    "matched":    str,   # Best taxonomy match
                    "score":      float, # Match confidence (0–1)
                    "method":     str,   # Match method used
                    "normalized": str,   # Normalized form
                }
            ]
        """
        self._ensure_loaded()
        threshold = threshold or settings.SKILLS_FUZZY_THRESHOLD

        results = []
        for skill in skills:
            if not skill or not skill.strip():
                continue
            match_result = self._match_single(skill.strip(), threshold)
            results.append(match_result)

        return results

    def match_and_normalize(
        self,
        skills: list[str],
        threshold: Optional[int] = None,
    ) -> list[str]:
        """
        Match and return only the normalized skill names.
        Filters out low-confidence matches.
        """
        results = self.match(skills, threshold)
        normalized = [
            r["normalized"]
            for r in results
            if r["score"] >= 0.60 and r["normalized"]
        ]
        return deduplicate(normalized)

    # ─── Single Skill Matching ─────────────────────────────────────────────────
    def _match_single(self, skill: str, threshold: int) -> dict:
        """
        Match a single skill using the layered matching strategy.
        """
        original = skill
        skill_lower = skill.lower().strip()

        # ── Layer 1: Exact match ───────────────────────────────────────────────
        if skill_lower in self._taxonomy_set:
            return self._result(original, skill_lower, 1.0, "exact")

        # ── Layer 2: Alias match ───────────────────────────────────────────────
        if skill_lower in self.ALIAS_MAP:
            canonical = self.ALIAS_MAP[skill_lower]
            return self._result(original, canonical, 0.95, "alias")

        # ── Layer 3: Normalized match ──────────────────────────────────────────
        norm_key = self._normalize_key(skill_lower)
        if norm_key in self._normalized_lookup:
            matched = self._normalized_lookup[norm_key]
            return self._result(original, matched, 0.92, "normalized")

        # ── Layer 4: Fuzzy match ───────────────────────────────────────────────
        fuzzy_result = process.extractOne(
            skill_lower,
            self._taxonomy,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=threshold,
        )
        if fuzzy_result:
            matched, score, _ = fuzzy_result
            return self._result(
                original, matched,
                round(score / 100, 2),
                "fuzzy"
            )

        # ── Layer 5: Substring match ───────────────────────────────────────────
        substring_match = self._substring_match(skill_lower)
        if substring_match:
            return self._result(original, substring_match, 0.70, "substring")

        # ── No match: return original ──────────────────────────────────────────
        return self._result(original, skill, 0.50, "unmatched")

    def _substring_match(self, skill: str) -> Optional[str]:
        """
        Check if skill is a substring of (or contains) a taxonomy entry.
        """
        # skill contains a known skill
        for taxonomy_skill in self._taxonomy:
            if taxonomy_skill in skill and len(taxonomy_skill) >= 4:
                return taxonomy_skill

        # known skill contains the input skill
        for taxonomy_skill in self._taxonomy:
            if skill in taxonomy_skill and len(skill) >= 4:
                return taxonomy_skill

        return None

    # ─── Normalization ─────────────────────────────────────────────────────────
    def normalize_skill(self, skill: str) -> str:
        """
        Normalize a single skill to its canonical form.
        """
        self._ensure_loaded()
        result = self._match_single(skill.strip(), 80)
        return result["normalized"] or skill

    def normalize_skills_list(self, skills: list[str]) -> list[str]:
        """Normalize a list of skills."""
        return [self.normalize_skill(s) for s in skills if s]

    # ─── Deduplication ─────────────────────────────────────────────────────────
    def deduplicate_skills(self, skills: list[str]) -> list[str]:
        """
        Remove near-duplicate skills from a list.
        Example: ["JavaScript", "JS", "javascript"] → ["javascript"]
        """
        self._ensure_loaded()
        normalized = self.normalize_skills_list(skills)
        return deduplicate(normalized)

    # ─── Grouping ──────────────────────────────────────────────────────────────
    def group_related_skills(
        self,
        skills: list[str],
    ) -> dict[str, list[str]]:
        """
        Group skills into related clusters.
        Example: ["react", "vue", "angular"] → {"frontend_frameworks": [...]}
        """
        groups = {
            "frontend":  [],
            "backend":   [],
            "database":  [],
            "cloud":     [],
            "devops":    [],
            "data":      [],
            "mobile":    [],
            "other":     [],
        }

        frontend_skills  = {"react", "vue", "angular", "next.js", "nuxt.js",
                            "jquery", "bootstrap", "tailwind", "html", "css",
                            "sass", "webpack", "vite", "redux"}
        backend_skills   = {"django", "flask", "fastapi", "spring", "express",
                            "node.js", "rails", "laravel", "asp.net", ".net",
                            "nestjs", "graphql", "rest api"}
        database_skills  = {"mysql", "postgresql", "mongodb", "redis",
                            "elasticsearch", "sqlite", "oracle", "cassandra",
                            "dynamodb", "firebase", "sql server"}
        cloud_skills     = {"aws", "azure", "gcp", "google cloud",
                            "cloudformation", "terraform", "pulumi"}
        devops_skills    = {"docker", "kubernetes", "jenkins", "gitlab ci",
                            "github actions", "ansible", "ci/cd", "helm",
                            "prometheus", "grafana"}
        data_skills      = {"machine learning", "deep learning", "nlp",
                            "tensorflow", "pytorch", "scikit-learn", "pandas",
                            "numpy", "spark", "hadoop", "tableau", "power bi"}
        mobile_skills    = {"ios", "android", "swift", "kotlin", "react native",
                            "flutter", "dart", "xamarin"}

        for skill in skills:
            skill_lower = skill.lower()
            if skill_lower in frontend_skills:
                groups["frontend"].append(skill)
            elif skill_lower in backend_skills:
                groups["backend"].append(skill)
            elif skill_lower in database_skills:
                groups["database"].append(skill)
            elif skill_lower in cloud_skills:
                groups["cloud"].append(skill)
            elif skill_lower in devops_skills:
                groups["devops"].append(skill)
            elif skill_lower in data_skills:
                groups["data"].append(skill)
            elif skill_lower in mobile_skills:
                groups["mobile"].append(skill)
            else:
                groups["other"].append(skill)

        return {k: v for k, v in groups.items() if v}

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _normalize_key(self, text: str) -> str:
        """
        Create a normalized lookup key:
        lowercase, remove punctuation, collapse spaces.
        """
        key = text.lower()
        key = re.sub(r"[^\w\s]", "", key)
        key = re.sub(r"\s+", " ", key).strip()
        return key

    def _result(
        self,
        original:   str,
        matched:    str,
        score:      float,
        method:     str,
    ) -> dict:
        """Build a standardized match result dict."""
        return {
            "original":   original,
            "matched":    matched,
            "score":      score,
            "method":     method,
            "normalized": matched.lower().strip(),
        }

    # ─── Statistics ────────────────────────────────────────────────────────────
    def get_match_statistics(
        self,
        match_results: list[dict],
    ) -> dict:
        """
        Summarize match results statistics.
        """
        if not match_results:
            return {}

        methods = {}
        total_score = 0.0

        for result in match_results:
            method = result.get("method", "unknown")
            methods[method] = methods.get(method, 0) + 1
            total_score += result.get("score", 0)

        return {
            "total":         len(match_results),
            "avg_confidence":round(total_score / len(match_results), 3),
            "by_method":     methods,
            "high_conf":     sum(1 for r in match_results if r["score"] >= 0.85),
            "low_conf":      sum(1 for r in match_results if r["score"] <  0.60),
        }


# ─── Singleton ─────────────────────────────────────────────────────────────────
skills_matcher = SkillsMatcher()
