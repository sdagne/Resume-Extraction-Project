# Score confidence per extracted field
# app/validation/confidence_scorer.py

from typing import Optional

from app.utils.logger import get_logger
from app.utils.constants import Confidence
from app.models.schemas.extracted_data import ExtractedResumeSchema

logger = get_logger(__name__)


class ConfidenceScorer:
    """
    Calculates confidence scores for extracted resume data.

    Scores are based on:
      - Field completeness (how many fields were found)
      - Field quality (are values valid and well-formed)
      - Section coverage (how many sections were detected)
      - Cross-field consistency (dates make sense, etc.)

    All scores are in range 0.0 – 1.0
    """

    # ─── Field Weights ─────────────────────────────────────────────────────────
    CONTACT_WEIGHTS = {
        "full_name": 0.30,
        "email":     0.25,
        "phone":     0.20,
        "linkedin":  0.10,
        "city":      0.08,
        "country":   0.07,
    }

    EXPERIENCE_FIELD_WEIGHTS = {
        "job_title":      0.35,
        "company":        0.30,
        "start_date":     0.15,
        "end_date":       0.10,
        "description":    0.10,
    }

    EDUCATION_FIELD_WEIGHTS = {
        "degree":          0.35,
        "institution":     0.35,
        "graduation_date": 0.20,
        "field_of_study":  0.10,
    }

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def score(
        self,
        schema: ExtractedResumeSchema,
    ) -> dict:
        """
        Calculate comprehensive confidence scores for the schema.

        Returns:
            {
                "contact":        float,
                "summary":        float,
                "experience":     float,
                "education":      float,
                "skills":         float,
                "certifications": float,
                "projects":       float,
                "overall":        float,
                "level":          str,
                "breakdown":      dict,
            }
        """
        scores = {}

        # ── Per-section scores ─────────────────────────────────────────────────
        scores["contact"]        = self._score_contact(schema)
        scores["summary"]        = self._score_summary(schema)
        scores["experience"]     = self._score_experience(schema)
        scores["education"]      = self._score_education(schema)
        scores["skills"]         = self._score_skills(schema)
        scores["certifications"] = self._score_certifications(schema)
        scores["projects"]       = self._score_projects(schema)

        # ── Section coverage bonus ─────────────────────────────────────────────
        coverage_bonus = self._score_section_coverage(schema)

        # ── Overall weighted score ─────────────────────────────────────────────
        weights = {
            "contact":        0.28,
            "experience":     0.25,
            "education":      0.18,
            "skills":         0.15,
            "summary":        0.06,
            "certifications": 0.04,
            "projects":       0.04,
        }

        weighted_sum = sum(
            scores.get(field, 0) * weight
            for field, weight in weights.items()
        )

        # Apply coverage bonus (up to 5% extra)
        overall = min(1.0, weighted_sum + coverage_bonus * 0.05)
        scores["overall"] = round(overall, 3)

        # ── Confidence level ───────────────────────────────────────────────────
        if overall >= Confidence.HIGH_THRESHOLD:
            scores["level"] = Confidence.HIGH
        elif overall >= Confidence.MEDIUM_THRESHOLD:
            scores["level"] = Confidence.MEDIUM
        else:
            scores["level"] = Confidence.LOW

        # ── Breakdown ─────────────────────────────────────────────────────────
        scores["breakdown"] = {
            "section_coverage":    coverage_bonus,
            "has_contact":         bool(schema.contact.full_name),
            "has_experience":      bool(schema.experience),
            "has_education":       bool(schema.education),
            "has_skills":          bool(schema.skills.all),
            "experience_count":    len(schema.experience),
            "education_count":     len(schema.education),
            "skills_count":        len(schema.skills.all),
            "certifications_count":len(schema.certifications),
        }

        logger.debug(
            f"Confidence scores: overall={overall:.3f} "
            f"({scores['level']})"
        )
        return scores

    # ─── Section Scorers ───────────────────────────────────────────────────────
    def _score_contact(self, schema: ExtractedResumeSchema) -> float:
        """Score contact information completeness."""
        contact = schema.contact
        score   = 0.0

        field_map = {
            "full_name": contact.full_name,
            "email":     contact.email,
            "phone":     contact.phone,
            "linkedin":  contact.linkedin,
            "city":      contact.city,
            "country":   contact.country,
        }

        for field, value in field_map.items():
            if value:
                score += self.CONTACT_WEIGHTS.get(field, 0)

        return round(score, 3)

    def _score_summary(self, schema: ExtractedResumeSchema) -> float:
        """Score summary quality."""
        if not schema.summary:
            return 0.0

        length = len(schema.summary)
        if length >= 200:
            return 1.0
        elif length >= 100:
            return 0.8
        elif length >= 50:
            return 0.6
        else:
            return 0.3

    def _score_experience(self, schema: ExtractedResumeSchema) -> float:
        """Score experience entries quality."""
        if not schema.experience:
            return 0.0

        entry_scores = []
        for exp in schema.experience:
            entry_score = 0.0
            field_map = {
                "job_title":   exp.job_title,
                "company":     exp.company,
                "start_date":  exp.start_date,
                "end_date":    exp.end_date or (
                    "Present" if exp.is_current else None
                ),
                "description": exp.description or (
                    exp.responsibilities[0] if exp.responsibilities else None
                ),
            }
            for field, value in field_map.items():
                if value:
                    entry_score += self.EXPERIENCE_FIELD_WEIGHTS.get(field, 0)
            entry_scores.append(entry_score)

        # Average score across all entries
        avg = sum(entry_scores) / len(entry_scores)

        # Bonus for multiple entries (up to 3)
        count_bonus = min(len(schema.experience), 3) / 3 * 0.10

        return round(min(1.0, avg + count_bonus), 3)

    def _score_education(self, schema: ExtractedResumeSchema) -> float:
        """Score education entries quality."""
        if not schema.education:
            return 0.0

        entry_scores = []
        for edu in schema.education:
            entry_score = 0.0
            field_map = {
                "degree":          edu.degree,
                "institution":     edu.institution,
                "graduation_date": edu.graduation_date,
                "field_of_study":  edu.field_of_study,
            }
            for field, value in field_map.items():
                if value:
                    entry_score += self.EDUCATION_FIELD_WEIGHTS.get(field, 0)
            entry_scores.append(entry_score)

        return round(
            sum(entry_scores) / len(entry_scores), 3
        )

    def _score_skills(self, schema: ExtractedResumeSchema) -> float:
        """Score skills completeness and diversity."""
        all_skills = schema.skills.all
        if not all_skills:
            return 0.0

        count = len(all_skills)

        # Base score from count
        if count >= 15:
            base = 1.0
        elif count >= 10:
            base = 0.85
        elif count >= 5:
            base = 0.65
        elif count >= 3:
            base = 0.45
        else:
            base = 0.25

        # Diversity bonus: skills across multiple categories
        categories_with_skills = sum(1 for cat in [
            schema.skills.technical,
            schema.skills.frameworks,
            schema.skills.databases,
            schema.skills.tools,
            schema.skills.soft,
        ] if cat)

        diversity_bonus = categories_with_skills / 5 * 0.10

        return round(min(1.0, base + diversity_bonus), 3)

    def _score_certifications(self, schema: ExtractedResumeSchema) -> float:
        """Score certifications."""
        if not schema.certifications:
            return 0.0

        # Score based on completeness of each cert
        scores = []
        for cert in schema.certifications:
            cert_score = 0.0
            if cert.name:   cert_score += 0.50
            if cert.issuer: cert_score += 0.30
            if cert.date:   cert_score += 0.20
            scores.append(cert_score)

        return round(sum(scores) / len(scores), 3)

    def _score_projects(self, schema: ExtractedResumeSchema) -> float:
        """Score projects."""
        if not schema.projects:
            return 0.0

        scores = []
        for proj in schema.projects:
            proj_score = 0.0
            if proj.name:         proj_score += 0.40
            if proj.description:  proj_score += 0.30
            if proj.technologies: proj_score += 0.30
            scores.append(proj_score)

        return round(sum(scores) / len(scores), 3)

    def _score_section_coverage(
        self,
        schema: ExtractedResumeSchema,
    ) -> float:
        """
        Score how many resume sections were detected.
        Returns 0.0 – 1.0
        """
        sections = [
            bool(schema.contact.full_name or schema.contact.email),
            bool(schema.summary),
            bool(schema.experience),
            bool(schema.education),
            bool(schema.skills.all),
            bool(schema.certifications),
            bool(schema.projects),
            bool(schema.languages),
        ]

        return round(sum(sections) / len(sections), 3)

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def get_confidence_label(self, score: float) -> str:
        """Convert numeric score to label."""
        if score >= Confidence.HIGH_THRESHOLD:
            return Confidence.HIGH
        elif score >= Confidence.MEDIUM_THRESHOLD:
            return Confidence.MEDIUM
        else:
            return Confidence.LOW

    def compare_schemas(
        self,
        schema_a: ExtractedResumeSchema,
        schema_b: ExtractedResumeSchema,
    ) -> dict:
        """
        Compare confidence scores of two schemas.
        Useful for choosing the better extraction result.
        """
        scores_a = self.score(schema_a)
        scores_b = self.score(schema_b)

        return {
            "schema_a_overall": scores_a["overall"],
            "schema_b_overall": scores_b["overall"],
            "better":           "a" if scores_a["overall"] >= scores_b["overall"] else "b",
            "difference":       round(
                abs(scores_a["overall"] - scores_b["overall"]), 3
            ),
        }


# ─── Singleton ─────────────────────────────────────────────────────────────────
confidence_scorer = ConfidenceScorer()
