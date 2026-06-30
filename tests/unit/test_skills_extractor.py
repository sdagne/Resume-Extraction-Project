
# tests/unit/test_skills_extractor.py

import pytest
from app.extraction.skills_extractor import SkillsExtractor


@pytest.fixture
def extractor():
    return SkillsExtractor()


class TestSkillsSectionParsing:

    def test_parses_comma_separated(self, extractor):
        text   = "Python, Java, React, Docker"
        result = extractor._parse_skills_section(text)
        assert "Python" in result
        assert "Java"   in result
        assert "React"  in result
        assert "Docker" in result

    def test_parses_bullet_points(self, extractor):
        text = "• Python\n• Java\n• Docker\n• Kubernetes"
        result = extractor._parse_skills_section(text)
        assert len(result) >= 3

    def test_parses_categorized_skills(self, extractor):
        text = """
Languages: Python, Java, Go
Frameworks: Django, Spring Boot
Databases: PostgreSQL, MongoDB
        """
        result = extractor._parse_skills_section(text)
        assert "Python" in result or "python" in [r.lower() for r in result]
        assert "Django" in result or "django" in [r.lower() for r in result]

    def test_parses_pipe_separated(self, extractor):
        text   = "Python | Java | React | Docker"
        result = extractor._parse_skills_section(text)
        assert len(result) >= 3

    def test_skips_empty_lines(self, extractor):
        text   = "Python\n\nJava\n\nReact"
        result = extractor._parse_skills_section(text)
        assert len([r for r in result if r]) >= 2


class TestSkillValidation:

    def test_valid_skill(self, extractor):
        assert extractor._is_valid_skill("Python")   is True
        assert extractor._is_valid_skill("React.js") is True
        assert extractor._is_valid_skill("CI/CD")    is True

    def test_rejects_digits_only(self, extractor):
        assert extractor._is_valid_skill("12345") is False

    def test_rejects_too_short(self, extractor):
        assert extractor._is_valid_skill("a") is False

    def test_rejects_stop_words(self, extractor):
        assert extractor._is_valid_skill("the")        is False
        assert extractor._is_valid_skill("experience") is False

    def test_rejects_no_letters(self, extractor):
        assert extractor._is_valid_skill("123-456") is False


class TestSkillCategorization:

    def test_categorizes_programming_languages(self, extractor):
        skills = ["python", "java", "javascript", "typescript"]
        result = extractor._categorize_skills(skills)
        assert len(result["programming_languages"]) >= 3

    def test_categorizes_frameworks(self, extractor):
        skills = ["django", "react", "spring boot", "fastapi"]
        result = extractor._categorize_skills(skills)
        assert len(result["frameworks"]) >= 2

    def test_categorizes_databases(self, extractor):
        skills = ["postgresql", "mongodb", "redis"]
        result = extractor._categorize_skills(skills)
        assert len(result["databases"]) >= 2

    def test_uncategorized_goes_to_other(self, extractor):
        skills = ["some_unknown_skill_xyz"]
        result = extractor._categorize_skills(skills)
        assert "some_unknown_skill_xyz" in result["other"]


class TestFullSkillsExtraction:

    def test_full_extraction(self, extractor, sample_skills_text):
        result = extractor.extract(sample_skills_text)
        assert len(result["all"]) > 0
        assert isinstance(result["all"], list)

    def test_returns_all_key(self, extractor, sample_skills_text):
        result = extractor.extract(sample_skills_text)
        assert "all" in result

    def test_no_duplicates_in_all(self, extractor, sample_skills_text):
        result = extractor.extract(sample_skills_text)
        assert len(result["all"]) == len(set(result["all"]))

    def test_empty_text_returns_empty(self, extractor):
        result = extractor.extract("")
        assert result["all"] == []

    def test_mines_skills_from_full_text(self, extractor):
        full_text = """
        I have 5 years of experience with Python and built
        microservices using Docker and Kubernetes on AWS.
        """
        result = extractor.extract("", full_resume_text=full_text)
        skills_lower = [s.lower() for s in result["all"]]
        assert "python" in skills_lower or "docker" in skills_lower
