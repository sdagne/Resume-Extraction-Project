
# tests/unit/test_section_segmentor.py

import pytest
from app.extraction.section_segmentor import SectionSegmentor
from app.utils.constants import SectionName


@pytest.fixture
def segmentor():
    return SectionSegmentor()


class TestKeywordMatching:

    def test_matches_experience_keywords(self, segmentor):
        assert segmentor._match_keyword("Work Experience") == SectionName.EXPERIENCE
        assert segmentor._match_keyword("Employment History") == SectionName.EXPERIENCE
        assert segmentor._match_keyword("Professional Experience") == SectionName.EXPERIENCE

    def test_matches_education_keywords(self, segmentor):
        assert segmentor._match_keyword("Education") == SectionName.EDUCATION
        assert segmentor._match_keyword("Academic Background") == SectionName.EDUCATION

    def test_matches_skills_keywords(self, segmentor):
        assert segmentor._match_keyword("Skills") == SectionName.SKILLS
        assert segmentor._match_keyword("Technical Skills") == SectionName.SKILLS
        assert segmentor._match_keyword("Core Competencies") == SectionName.SKILLS

    def test_matches_certifications_keywords(self, segmentor):
        assert segmentor._match_keyword("Certifications") == SectionName.CERTIFICATIONS
        assert segmentor._match_keyword("Professional Certifications") == SectionName.CERTIFICATIONS

    def test_matches_projects_keywords(self, segmentor):
        assert segmentor._match_keyword("Projects") == SectionName.PROJECTS
        assert segmentor._match_keyword("Personal Projects") == SectionName.PROJECTS

    def test_returns_none_for_unknown(self, segmentor):
        assert segmentor._match_keyword("Random Text Here") is None

    def test_case_insensitive_matching(self, segmentor):
        assert segmentor._match_keyword("WORK EXPERIENCE") == SectionName.EXPERIENCE
        assert segmentor._match_keyword("work experience") == SectionName.EXPERIENCE


class TestAllCapsDetection:

    def test_detects_all_caps(self, segmentor):
        assert segmentor._is_all_caps("WORK EXPERIENCE") is True
        assert segmentor._is_all_caps("EDUCATION")       is True

    def test_rejects_mixed_case(self, segmentor):
        assert segmentor._is_all_caps("Work Experience") is False

    def test_rejects_short_text(self, segmentor):
        assert segmentor._is_all_caps("AB") is False

    def test_handles_text_with_numbers(self, segmentor):
        # Numbers don't affect all-caps detection
        assert segmentor._is_all_caps("SKILLS 2024") is True


class TestHeaderDetection:

    def test_detects_bold_header(self, segmentor):
        result = segmentor._detect_section_header(
            text="Work Experience",
            font_size=12.0,
            is_bold=True,
            is_header=False,
            y0=100,
            page_height=842,
            block_index=5,
            total_blocks=50,
        )
        assert result == SectionName.EXPERIENCE

    def test_detects_large_font_header(self, segmentor):
        result = segmentor._detect_section_header(
            text="Education",
            font_size=14.0,
            is_bold=False,
            is_header=False,
            y0=200,
            page_height=842,
            block_index=10,
            total_blocks=50,
        )
        assert result == SectionName.EDUCATION

    def test_ignores_long_text(self, segmentor):
        long_text = "This is a very long sentence that cannot possibly be a section header in any resume format"
        result = segmentor._detect_section_header(
            text=long_text,
            font_size=14.0,
            is_bold=True,
            is_header=False,
            y0=100,
            page_height=842,
            block_index=5,
            total_blocks=50,
        )
        assert result is None

    def test_ignores_date_ranges(self, segmentor):
        result = segmentor._detect_section_header(
            text="Jan 2020 - Present",
            font_size=12.0,
            is_bold=True,
            is_header=False,
            y0=100,
            page_height=842,
            block_index=5,
            total_blocks=50,
        )
        assert result is None


class TestFullSegmentation:

    def test_segments_from_text(self, segmentor, sample_resume_text):
        result = segmentor.segment_from_text(sample_resume_text)
        assert isinstance(result, dict)
        # Should detect at least experience and education
        assert result.get(SectionName.EXPERIENCE) or \
               result.get(SectionName.EDUCATION)

    def test_returns_all_section_keys(self, segmentor):
        result = segmentor.segment_from_text("Some text")
        for section in SectionName.ALL:
            assert section in result

    def test_empty_text_returns_empty_sections(self, segmentor):
        result = segmentor.segment_from_text("")
        for section in SectionName.ALL:
            assert result[section] == "" or result[section] == []
