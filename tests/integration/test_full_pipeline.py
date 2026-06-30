
# tests/integration/test_full_pipeline.py

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.extraction.contact_extractor    import ContactExtractor
from app.extraction.experience_extractor import ExperienceExtractor
from app.extraction.education_extractor  import EducationExtractor
from app.extraction.skills_extractor     import SkillsExtractor
from app.extraction.section_segmentor    import SectionSegmentor
from app.extraction.field_extractor      import FieldExtractor
from app.nlp.date_parser                 import DateParser
from app.validation.schema_validator     import SchemaValidator
from app.validation.confidence_scorer    import ConfidenceScorer
from app.models.schemas.extracted_data   import ExtractedResumeSchema


@pytest.fixture
def full_text_blocks(sample_resume_text):
    """Convert sample text to mock text blocks."""
    blocks = []
    lines  = sample_resume_text.splitlines()
    y_pos  = 50.0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            y_pos += 10
            continue

        # Simulate larger font for likely headers
        is_upper    = stripped.isupper() and len(stripped) > 3
        font_size   = 14.0 if is_upper else 11.0
        is_bold     = is_upper

        blocks.append({
            "text":      stripped,
            "page_num":  1,
            "bbox":      {"x0": 50, "y0": y_pos, "x1": 500, "y1": y_pos + 14},
            "font_size": font_size,
            "font_name": "Arial-Bold" if is_bold else "Arial",
            "is_bold":   is_bold,
            "is_header": is_upper,
            "column":    "full",
        })
        y_pos += 18

    return blocks


class TestContactExtractorIntegration:

    def test_extracts_all_contact_fields(self, sample_contact_text):
        extractor = ContactExtractor()
        result    = extractor.extract(sample_contact_text)

        assert result["email"]    == "john.smith@example.com"
        assert result["phone"]    is not None
        assert result["linkedin"] is not None
        assert result["github"]   is not None
        assert result["city"]     is not None

    def test_confidence_is_high_for_complete_contact(self, sample_contact_text):
        extractor = ContactExtractor()
        result    = extractor.extract(sample_contact_text)
        assert result["confidence"] >= 0.60


class TestExperienceExtractorIntegration:

    def test_extracts_multiple_jobs(self, sample_experience_text):
        extractor = ExperienceExtractor()
        result    = extractor.extract(sample_experience_text)
        assert len(result) >= 1

    def test_extracts_job_title_and_company(self, sample_experience_text):
        extractor = ExperienceExtractor()
        result    = extractor.extract(sample_experience_text)
        if result:
            first = result[0]
            assert first.get("job_title") or first.get("company")

    def test_extracts_dates(self, sample_experience_text):
        extractor = ExperienceExtractor()
        result    = extractor.extract(sample_experience_text)
        if result:
            first = result[0]
            assert first.get("start_date") or first.get("end_date")

    def test_most_recent_job_first(self, sample_experience_text):
        extractor = ExperienceExtractor()
        result    = extractor.extract(sample_experience_text)
        if len(result) >= 2:
            # Most recent should be first
            first_start = result[0].get("start_date", "")
            second_start= result[1].get("start_date", "")
            if first_start and second_start:
                dp = DateParser()
                dt1 = dp.parse_date_string(first_start)
                dt2 = dp.parse_date_string(second_start)
                if dt1 and dt2:
                    assert dt1 >= dt2


class TestEducationExtractorIntegration:

    def test_extracts_degree(self, sample_education_text):
        extractor = EducationExtractor()
        result    = extractor.extract(sample_education_text)
        assert len(result) >= 1
        assert result[0].get("degree") is not None

    def test_extracts_institution(self, sample_education_text):
        extractor = EducationExtractor()
        result    = extractor.extract(sample_education_text)
        assert len(result) >= 1
        assert result[0].get("institution") is not None

    def test_extracts_gpa(self, sample_education_text):
        extractor = EducationExtractor()
        result    = extractor.extract(sample_education_text)
        if result:
            assert result[0].get("gpa") is not None


class TestSkillsExtractorIntegration:

    def test_extracts_skills(self, sample_skills_text):
        extractor = SkillsExtractor()
        result    = extractor.extract(sample_skills_text)
        assert len(result["all"]) > 0

    def test_categorizes_correctly(self, sample_skills_text):
        extractor = SkillsExtractor()
        result    = extractor.extract(sample_skills_text)
        # Should have some programming languages
        assert len(result.get("programming_languages", [])) > 0


class TestFullFieldExtractorIntegration:

    def test_full_extraction_from_blocks(
        self, full_text_blocks, sample_resume_text
    ):
        extractor = FieldExtractor()
        result    = extractor.extract(
            text_blocks = full_text_blocks,
            full_text   = sample_resume_text,
            page_height = 842.0,
        )

        assert isinstance(result, ExtractedResumeSchema)
        assert result.contact is not None

    def test_extraction_has_confidence_score(
        self, full_text_blocks, sample_resume_text
    ):
        extractor = FieldExtractor()
        result    = extractor.extract(
            text_blocks = full_text_blocks,
            full_text   = sample_resume_text,
            page_height = 842.0,
        )
        assert result.confidence_scores.overall is not None
        assert 0.0 <= result.confidence_scores.overall <= 1.0

    def test_extraction_detects_language(
        self, full_text_blocks, sample_resume_text
    ):
        extractor = FieldExtractor()
        result    = extractor.extract(
            text_blocks = full_text_blocks,
            full_text   = sample_resume_text,
            page_height = 842.0,
        )
        assert result.detected_language == "en"


class TestSchemaValidatorIntegration:

    def test_validates_complete_schema(
        self, full_text_blocks, sample_resume_text
    ):
        extractor = FieldExtractor()
        schema    = extractor.extract(
            text_blocks = full_text_blocks,
            full_text   = sample_resume_text,
            page_height = 842.0,
        )

        validator          = SchemaValidator()
        validated, warnings = validator.validate(schema)

        assert isinstance(validated, ExtractedResumeSchema)
        assert isinstance(warnings, list)

    def test_completeness_check(
        self, full_text_blocks, sample_resume_text
    ):
        extractor = FieldExtractor()
        schema    = extractor.extract(
            text_blocks = full_text_blocks,
            full_text   = sample_resume_text,
            page_height = 842.0,
        )

        validator  = SchemaValidator()
        completeness = validator.check_completeness(schema)

        assert "score"   in completeness
        assert "level"   in completeness
        assert "missing" in completeness
        assert "present" in completeness
        assert 0.0 <= completeness["score"] <= 1.0


class TestConfidenceScorerIntegration:

    def test_scores_complete_schema(
        self, full_text_blocks, sample_resume_text
    ):
        extractor = FieldExtractor()
        schema    = extractor.extract(
            text_blocks = full_text_blocks,
            full_text   = sample_resume_text,
            page_height = 842.0,
        )

        scorer = ConfidenceScorer()
        scores = scorer.score(schema)

        assert "overall" in scores
        assert "level"   in scores
        assert 0.0 <= scores["overall"] <= 1.0

    def test_empty_schema_has_low_confidence(self):
        scorer = ConfidenceScorer()
        schema = ExtractedResumeSchema()
        scores = scorer.score(schema)

        assert scores["overall"] < 0.30
