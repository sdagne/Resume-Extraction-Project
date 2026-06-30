
# tests/unit/test_date_parser.py

import pytest
from datetime import datetime
from app.nlp.date_parser import DateParser


@pytest.fixture
def parser():
    return DateParser()


class TestDateStringParsing:

    def test_parses_month_year(self, parser):
        result = parser.parse_date_string("January 2020")
        assert result is not None
        assert result.year  == 2020
        assert result.month == 1

    def test_parses_abbreviated_month(self, parser):
        result = parser.parse_date_string("Jan 2020")
        assert result is not None
        assert result.year == 2020

    def test_parses_year_only(self, parser):
        result = parser.parse_date_string("2020")
        assert result is not None
        assert result.year == 2020

    def test_parses_slash_format(self, parser):
        result = parser.parse_date_string("01/2020")
        assert result is not None
        assert result.year  == 2020
        assert result.month == 1

    def test_returns_none_for_invalid(self, parser):
        result = parser.parse_date_string("not a date")
        assert result is None

    def test_returns_none_for_empty(self, parser):
        result = parser.parse_date_string("")
        assert result is None

    def test_present_returns_current_date(self, parser):
        result = parser.parse_date_string("Present")
        assert result is not None
        assert result.year == datetime.now().year


class TestDateRangeParsing:

    def test_parses_full_date_range(self, parser):
        result = parser.parse_date_range("Jan 2018 - Mar 2021")
        assert result["start_date"]  is not None
        assert result["end_date"]    is not None
        assert result["is_current"]  is False

    def test_parses_present_range(self, parser):
        result = parser.parse_date_range("Jan 2020 - Present")
        assert result["is_current"]  is True
        assert result["start_date"]  is not None

    def test_calculates_duration(self, parser):
        result = parser.parse_date_range("Jan 2020 - Jan 2022")
        assert result["duration_years"] is not None
        assert abs(result["duration_years"] - 2.0) < 0.2

    def test_parses_year_only_range(self, parser):
        result = parser.parse_date_range("2018 - 2021")
        assert result["start_date"] is not None
        assert result["end_date"]   is not None

    def test_handles_em_dash_separator(self, parser):
        result = parser.parse_date_range("Jan 2018 – Mar 2021")
        assert result["start_date"] is not None


class TestDateNormalization:

    def test_normalizes_to_mon_year(self, parser):
        result = parser.normalize_date("January 2020")
        assert result == "Jan 2020"

    def test_normalizes_slash_format(self, parser):
        result = parser.normalize_date("01/2020")
        assert result == "Jan 2020"

    def test_normalizes_year_only(self, parser):
        result = parser.normalize_date("2020")
        assert result == "2020"

    def test_normalizes_present(self, parser):
        result = parser.normalize_date("present")
        assert result == "Present"

    def test_returns_none_for_empty(self, parser):
        result = parser.normalize_date(None)
        assert result is None


class TestTotalExperience:

    def test_calculates_non_overlapping(self, parser):
        ranges = [
            {
                "start_datetime": datetime(2018, 1, 1),
                "end_datetime":   datetime(2020, 1, 1),
            },
            {
                "start_datetime": datetime(2020, 6, 1),
                "end_datetime":   datetime(2022, 6, 1),
            },
        ]
        total = parser.get_total_experience(ranges)
        assert abs(total - 4.0) < 0.3

    def test_merges_overlapping_periods(self, parser):
        ranges = [
            {
                "start_datetime": datetime(2018, 1, 1),
                "end_datetime":   datetime(2021, 1, 1),
            },
            {
                "start_datetime": datetime(2019, 1, 1),
                "end_datetime":   datetime(2022, 1, 1),
            },
        ]
        total = parser.get_total_experience(ranges)
        # Should be ~4 years (merged), not 6
        assert total <= 4.5

    def test_returns_zero_for_empty(self, parser):
        assert parser.get_total_experience([]) == 0.0
