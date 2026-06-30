
# tests/unit/test_contact_extractor.py

import pytest
from app.extraction.contact_extractor import ContactExtractor


@pytest.fixture
def extractor():
    return ContactExtractor()


class TestEmailExtraction:

    def test_extracts_standard_email(self, extractor):
        text   = "Contact me at john.smith@gmail.com for more info"
        result = extractor._extract_email(text)
        assert result == "john.smith@gmail.com"

    def test_extracts_email_with_plus(self, extractor):
        text   = "Email: john+work@company.co.uk"
        result = extractor._extract_email(text)
        assert result == "john+work@company.co.uk"

    def test_returns_none_for_invalid_email(self, extractor):
        result = extractor._extract_email("no email here")
        assert result is None

    def test_email_is_lowercased(self, extractor):
        result = extractor._extract_email("John.Smith@Gmail.COM")
        assert result == "john.smith@gmail.com"

    def test_extracts_from_multiline_text(self, extractor):
        text = "Name: John\nEmail: john@example.com\nPhone: 123"
        assert extractor._extract_email(text) == "john@example.com"


class TestPhoneExtraction:

    def test_extracts_us_phone(self, extractor):
        text   = "Call me: +1 (555) 123-4567"
        result = extractor._extract_phone(text)
        assert result is not None
        assert "555" in result

    def test_extracts_international_phone(self, extractor):
        text   = "Phone: +44 20 7946 0958"
        result = extractor._extract_phone(text)
        assert result is not None

    def test_returns_none_for_short_number(self, extractor):
        result = extractor._extract_phone("12345")
        assert result is None

    def test_extracts_phone_without_country_code(self, extractor):
        text   = "Tel: 555-867-5309"
        result = extractor._extract_phone(text)
        assert result is not None


class TestLinkedInExtraction:

    def test_extracts_full_linkedin_url(self, extractor):
        text   = "https://www.linkedin.com/in/johnsmith"
        result = extractor._extract_linkedin(text)
        assert result == "https://linkedin.com/in/johnsmith"

    def test_extracts_linkedin_without_https(self, extractor):
        text   = "linkedin.com/in/john-smith-123"
        result = extractor._extract_linkedin(text)
        assert "john-smith-123" in result

    def test_returns_none_for_no_linkedin(self, extractor):
        result = extractor._extract_linkedin("no social media here")
        assert result is None


class TestNameExtraction:

    def test_extracts_name_from_first_line(self, extractor):
        text   = "John Smith\nSoftware Engineer\njohn@email.com"
        result = extractor._name_from_first_line(text)
        assert result is not None
        assert "John" in result or "Smith" in result

    def test_skips_email_lines(self, extractor):
        text   = "john@email.com\nJohn Smith\nEngineer"
        result = extractor._name_from_first_line(text)
        # Should skip the email line
        assert "@" not in (result or "")

    def test_cleans_name_prefix(self, extractor):
        result = extractor._clean_name("Dr. John Smith")
        assert "Dr." not in result
        assert "John Smith" in result

    def test_cleans_credentials_suffix(self, extractor):
        result = extractor._clean_name("John Smith, PhD")
        assert "PhD" not in result


class TestFullContactExtraction:

    def test_full_extraction(self, extractor, sample_contact_text):
        result = extractor.extract(sample_contact_text)
        assert result["email"]    == "john.smith@example.com"
        assert result["phone"]    is not None
        assert result["linkedin"] is not None
        assert result["github"]   is not None

    def test_confidence_score_range(self, extractor, sample_contact_text):
        result = extractor.extract(sample_contact_text)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_high_confidence_for_complete_contact(
        self, extractor, sample_contact_text
    ):
        result = extractor.extract(sample_contact_text)
        assert result["confidence"] >= 0.5

    def test_empty_text_returns_none_fields(self, extractor):
        result = extractor.extract("")
        assert result["email"]    is None
        assert result["phone"]    is None
        assert result["full_name"]is None
