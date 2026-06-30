# app/extraction/field_extractor.py

import time
from typing import Optional

from app.utils.logger import get_logger
from app.utils.constants import SectionName
from app.utils.helpers import remove_empty_fields
from app.models.schemas.extracted_data import (
    ExtractedResumeSchema,
    ContactSchema,
    SkillsSchema,
    FieldConfidenceSchema,
)
from app.extraction.section_segmentor       import section_segmentor
from app.extraction.contact_extractor       import contact_extractor
from app.extraction.experience_extractor    import experience_extractor
from app.extraction.education_extractor     import education_extractor
from app.extraction.skills_extractor        import skills_extractor
from app.extraction.summary_extractor       import summary_extractor
from app.extraction.certifications_extractor import certifications_extractor
from app.extraction.projects_extractor      import projects_extractor
from app.nlp.language_detector             import language_detector
from app.nlp.date_parser                   import date_parser

logger = get_logger(__name__)


class FieldExtractor:
    """
    Master extractor that orchestrates the full extraction pipeline.

    Pipeline:
      1. Detect language
      2. Segment text into sections
      3. Run each field extractor on its section
      4. Calculate total experience
      5. Build confidence scores
      6. Return structured ExtractedResumeSchema
    """

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def extract(
        self,
        text_blocks: list[dict],
        full_text:   str,
        page_height: float = 0.0,
    ) -> ExtractedResumeSchema:
        """
        Run the full extraction pipeline on parsed document data.

        Args:
            text_blocks:  Ordered list of text blocks from parser
            full_text:    Full document text string
            page_height:  Page height for positional heuristics

        Returns:
            ExtractedResumeSchema with all extracted fields
        """
        start_time = time.time()
        warnings   = []

        logger.info(
            f"Starting field extraction: "
            f"{len(text_blocks)} blocks, "
            f"{len(full_text)} chars"
        )

        # ── Step 1: Detect language ────────────────────────────────────────────
        lang_result = language_detector.detect(full_text)
        detected_lang = lang_result["language"]
        logger.info(f"Detected language: {detected_lang}")

        # ── Step 2: Segment into sections ─────────────────────────────────────
        sections = section_segmentor.segment(text_blocks, page_height)
        detected_section_names = section_segmentor.get_detected_sections(sections)
        logger.info(f"Sections detected: {detected_section_names}")

        # ── Step 3: Get section texts ──────────────────────────────────────────
        def get_text(section_name: str) -> str:
            return section_segmentor.get_section_text(sections, section_name)

        contact_text        = get_text(SectionName.CONTACT)
        summary_text        = get_text(SectionName.SUMMARY)
        experience_text     = get_text(SectionName.EXPERIENCE)
        education_text      = get_text(SectionName.EDUCATION)
        skills_text         = get_text(SectionName.SKILLS)
        certifications_text = get_text(SectionName.CERTIFICATIONS)
        projects_text       = get_text(SectionName.PROJECTS)

        # ── Step 4: Extract each field ─────────────────────────────────────────

        # Contact
        contact_data = self._safe_extract(
            "contact",
            lambda: contact_extractor.extract(
                contact_text or full_text[:600],
                text_blocks,
            ),
            warnings,
        )

        # Summary
        summary = self._safe_extract(
            "summary",
            lambda: summary_extractor.extract(summary_text, full_text),
            warnings,
        )

        # Experience
        experience = self._safe_extract(
            "experience",
            lambda: experience_extractor.extract(experience_text),
            warnings,
            default=[],
        )

        # Education
        education = self._safe_extract(
            "education",
            lambda: education_extractor.extract(education_text),
            warnings,
            default=[],
        )

        # Skills
        skills_data = self._safe_extract(
            "skills",
            lambda: skills_extractor.extract(skills_text, full_text),
            warnings,
            default={},
        )

        # Certifications
        certifications = self._safe_extract(
            "certifications",
            lambda: certifications_extractor.extract(certifications_text),
            warnings,
            default=[],
        )

        # Projects
        projects = self._safe_extract(
            "projects",
            lambda: projects_extractor.extract(projects_text),
            warnings,
            default=[],
        )

        # ── Step 5: Calculate total experience ────────────────────────────────
        total_exp_years = self._calculate_total_experience(experience)

        # ── Step 6: Build confidence scores ───────────────────────────────────
        confidence = self._build_confidence_scores(
            contact_data, summary, experience,
            education, skills_data, certifications,
        )

        # ── Step 7: Build schema ───────────────────────────────────────────────
        result = ExtractedResumeSchema(
            contact    = ContactSchema(**(contact_data or {})),
            summary    = summary,
            experience = [
                self._map_experience(e) for e in (experience or [])
            ],
            education  = [
                self._map_education(e) for e in (education or [])
            ],
            skills     = self._map_skills(skills_data or {}),
            certifications = [
                self._map_certification(c) for c in (certifications or [])
            ],
            projects   = [
                self._map_project(p) for p in (projects or [])
            ],
            languages  = [],   # Handled by language_extractor if needed
            awards     = [],

            detected_language      = detected_lang,
            total_experience_years = total_exp_years,
            sections_detected      = detected_section_names,
            confidence_scores      = FieldConfidenceSchema(**confidence),
            extraction_warnings    = warnings,
            extraction_version     = "1.0.0",
        )

        duration = round(time.time() - start_time, 2)
        logger.info(
            f"Extraction complete in {duration}s | "
            f"confidence={confidence.get('overall', 0):.2f} | "
            f"warnings={len(warnings)}"
        )

        return result

    # ─── Safe Extraction ───────────────────────────────────────────────────────
    def _safe_extract(
        self,
        field_name: str,
        extractor_fn,
        warnings: list,
        default=None,
    ):
        """
        Run an extractor function safely.
        Catches exceptions and logs warnings instead of crashing.
        """
        try:
            result = extractor_fn()
            return result
        except Exception as e:
            msg = f"Extraction failed for '{field_name}': {str(e)}"
            logger.warning(msg)
            warnings.append(msg)
            return default

    # ─── Total Experience ──────────────────────────────────────────────────────
    def _calculate_total_experience(
        self,
        experience: list[dict],
    ) -> Optional[float]:
        """Calculate total years of experience from all entries."""
        if not experience:
            return None

        date_ranges = []
        for exp in experience:
            start_str = exp.get("start_date")
            end_str   = exp.get("end_date")

            start_dt = date_parser.parse_date_string(start_str)
            if exp.get("is_current"):
                from datetime import datetime
                end_dt = datetime.now()
            else:
                end_dt = date_parser.parse_date_string(end_str)

            if start_dt and end_dt:
                date_ranges.append({
                    "start_datetime": start_dt,
                    "end_datetime":   end_dt,
                })

        total = date_parser.get_total_experience(date_ranges)
        return total if total > 0 else None

    # ─── Confidence Scores ─────────────────────────────────────────────────────
    def _build_confidence_scores(
        self,
        contact:        Optional[dict],
        summary:        Optional[str],
        experience:     list,
        education:      list,
        skills:         dict,
        certifications: list,
    ) -> dict:
        """
        Build per-field and overall confidence scores.
        Scores are 0.0–1.0 based on extraction completeness.
        """
        scores = {}

        # Contact confidence
        scores["contact"] = (contact or {}).get("confidence", 0.0)

        # Summary confidence
        scores["summary"] = 0.8 if summary else 0.0

        # Experience confidence
        if experience:
            filled = sum(
                1 for e in experience
                if e.get("job_title") and e.get("company")
            )
            scores["experience"] = round(filled / len(experience), 2)
        else:
            scores["experience"] = 0.0

        # Education confidence
        if education:
            filled = sum(
                1 for e in education
                if e.get("degree") or e.get("institution")
            )
            scores["education"] = round(filled / len(education), 2)
        else:
            scores["education"] = 0.0

        # Skills confidence
        all_skills = (skills or {}).get("all", [])
        scores["skills"] = min(1.0, len(all_skills) / 10) if all_skills else 0.0

        # Certifications confidence
        scores["certifications"] = 0.8 if certifications else 0.0

        # Overall confidence (weighted average)
        weights = {
            "contact":        0.30,
            "experience":     0.25,
            "education":      0.20,
            "skills":         0.15,
            "summary":        0.05,
            "certifications": 0.05,
        }
        overall = sum(
            scores.get(field, 0) * weight
            for field, weight in weights.items()
        )
        scores["overall"] = round(overall, 3)

        return scores

    # ─── Schema Mappers ────────────────────────────────────────────────────────
    def _map_experience(self, exp: dict):
        from app.models.schemas.extracted_data import ExperienceItemSchema
        return ExperienceItemSchema(
            job_title        = exp.get("job_title"),
            company          = exp.get("company"),
            location         = exp.get("location"),
            start_date       = exp.get("start_date"),
            end_date         = exp.get("end_date"),
            duration_years   = exp.get("duration_years"),
            is_current       = exp.get("is_current", False),
            description      = exp.get("description"),
            responsibilities = exp.get("responsibilities", []),
        )

    def _map_education(self, edu: dict):
        from app.models.schemas.extracted_data import EducationItemSchema
        return EducationItemSchema(
            degree          = edu.get("degree"),
            field_of_study  = edu.get("field_of_study"),
            institution     = edu.get("institution"),
            location        = edu.get("location"),
            start_date      = edu.get("start_date"),
            graduation_date = edu.get("graduation_date"),
            gpa             = edu.get("gpa"),
        )

    def _map_skills(self, skills: dict):
        return SkillsSchema(
            technical  = skills.get("programming_languages", []),
            soft       = skills.get("soft_skills",           []),
            tools      = skills.get("tools",                 []),
            frameworks = skills.get("frameworks",            []),
            databases  = skills.get("databases",             []),
            languages  = [],
            all        = skills.get("all",                   []),
        )

    def _map_certification(self, cert: dict):
        from app.models.schemas.extracted_data import CertificationItemSchema
        return CertificationItemSchema(
            name          = cert.get("name"),
            issuer        = cert.get("issuer"),
            date          = cert.get("date"),
            expiry_date   = cert.get("expiry_date"),
            credential_id = cert.get("credential_id"),
        )

    def _map_project(self, proj: dict):
        from app.models.schemas.extracted_data import ProjectItemSchema
        return ProjectItemSchema(
            name         = proj.get("name"),
            description  = proj.get("description"),
            technologies = proj.get("technologies", []),
            url          = proj.get("url"),
            start_date   = proj.get("start_date"),
            end_date     = proj.get("end_date"),
        )


# ─── Singleton ─────────────────────────────────────────────────────────────────
field_extractor = FieldExtractor()
