# app/nlp/date_parser.py

import re
from datetime import datetime
from typing import Optional
from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta

from app.utils.logger import get_logger
from app.utils.constants import PRESENT_KEYWORDS, MONTH_ABBREVIATIONS
from app.utils import regex_patterns as patterns

logger = get_logger(__name__)


class DateParser:
    """
    Parses and normalizes date strings found in resumes.

    Handles:
      - Month-Year formats: "Jan 2020", "January 2020", "01/2020"
      - Year-only: "2020"
      - Date ranges: "Jan 2018 - Mar 2021", "2018 - Present"
      - Present/Current keywords
      - Various separators: -, –, —, to, /
    """

    # ─── Date Format Patterns ──────────────────────────────────────────────────
    MONTH_YEAR_FORMATS = [
        "%B %Y",    # January 2020
        "%b %Y",    # Jan 2020
        "%b. %Y",   # Jan. 2020
        "%m/%Y",    # 01/2020
        "%m-%Y",    # 01-2020
        "%Y-%m",    # 2020-01
        "%Y/%m",    # 2020/01
        "%B, %Y",   # January, 2020
        "%b, %Y",   # Jan, 2020
    ]

    FULL_DATE_FORMATS = [
        "%d %B %Y",   # 15 January 2020
        "%d %b %Y",   # 15 Jan 2020
        "%B %d, %Y",  # January 15, 2020
        "%b %d, %Y",  # Jan 15, 2020
        "%d/%m/%Y",   # 15/01/2020
        "%m/%d/%Y",   # 01/15/2020
        "%Y-%m-%d",   # 2020-01-15
    ]

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def parse_date_string(
        self,
        date_str: Optional[str],
    ) -> Optional[datetime]:
        """
        Parse a single date string into a datetime object.

        Returns None if parsing fails.
        """
        if not date_str:
            return None

        date_str = date_str.strip()

        # Handle present/current
        if self.is_present(date_str):
            return datetime.now()

        # Try structured formats first
        parsed = self._try_structured_formats(date_str)
        if parsed:
            return parsed

        # Try year-only
        year_match = patterns.YEAR.search(date_str)
        if year_match:
            try:
                return datetime(int(year_match.group()), 1, 1)
            except ValueError:
                pass

        # Try dateutil as last resort
        try:
            return dateutil_parser.parse(date_str, default=datetime(2000, 1, 1))
        except Exception:
            pass

        logger.debug(f"Could not parse date: '{date_str}'")
        return None

    def parse_date_range(
        self,
        text: str,
    ) -> dict:
        """
        Extract and parse a date range from text.

        Returns:
            {
                "start_date":     str | None,   # Normalized date string
                "end_date":       str | None,
                "start_datetime": datetime | None,
                "end_datetime":   datetime | None,
                "is_current":     bool,
                "duration_years": float | None,
                "raw_match":      str | None,
            }
        """
        result = {
            "start_date":     None,
            "end_date":       None,
            "start_datetime": None,
            "end_datetime":   None,
            "is_current":     False,
            "duration_years": None,
            "raw_match":      None,
        }

        match = patterns.DATE_RANGE.search(text)
        if not match:
            # Try to find a single date
            single = self._find_single_date(text)
            if single:
                result["start_date"]     = self.normalize_date(single)
                result["start_datetime"] = self.parse_date_string(single)
            return result

        raw_start = match.group(1).strip()
        raw_end   = match.group(2).strip()
        result["raw_match"] = match.group(0)

        # Parse start
        start_dt = self.parse_date_string(raw_start)
        if start_dt:
            result["start_date"]     = self.normalize_date(raw_start)
            result["start_datetime"] = start_dt

        # Parse end
        is_current = self.is_present(raw_end)
        result["is_current"] = is_current

        if is_current:
            result["end_date"]     = "Present"
            result["end_datetime"] = datetime.now()
        else:
            end_dt = self.parse_date_string(raw_end)
            if end_dt:
                result["end_date"]     = self.normalize_date(raw_end)
                result["end_datetime"] = end_dt

        # Calculate duration
        if result["start_datetime"] and result["end_datetime"]:
            result["duration_years"] = self._calculate_duration(
                result["start_datetime"],
                result["end_datetime"],
            )

        return result

    def extract_all_dates(self, text: str) -> list[dict]:
        """
        Extract all date mentions from text.

        Returns list of:
            {"raw": str, "normalized": str, "datetime": datetime, "type": str}
        """
        dates = []

        # Find all month-year patterns
        for match in patterns.MONTH_YEAR.finditer(text):
            raw = match.group(0)
            dt  = self.parse_date_string(raw)
            if dt:
                dates.append({
                    "raw":        raw,
                    "normalized": self.normalize_date(raw),
                    "datetime":   dt,
                    "type":       "month_year",
                })

        # Find year-only patterns (not already covered)
        covered_positions = {m.start() for m in patterns.MONTH_YEAR.finditer(text)}
        for match in patterns.YEAR.finditer(text):
            if match.start() not in covered_positions:
                raw = match.group(0)
                try:
                    dt = datetime(int(raw), 1, 1)
                    dates.append({
                        "raw":        raw,
                        "normalized": raw,
                        "datetime":   dt,
                        "type":       "year_only",
                    })
                except ValueError:
                    pass

        # Sort by position in text
        dates.sort(key=lambda d: text.find(d["raw"]))
        return dates

    # ─── Normalization ─────────────────────────────────────────────────────────
    def normalize_date(self, date_str: Optional[str]) -> Optional[str]:
        """
        Normalize a date string to "MMM YYYY" format.
        Example: "01/2020" → "Jan 2020", "2020" → "2020"
        """
        if not date_str:
            return None

        date_str = date_str.strip()

        if self.is_present(date_str):
            return "Present"

        dt = self.parse_date_string(date_str)
        if not dt:
            return date_str

        # Year-only input → return year only
        if re.match(r"^\d{4}$", date_str.strip()):
            return str(dt.year)

        return dt.strftime("%b %Y")

    def normalize_date_range(
        self,
        start: Optional[str],
        end: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        """Normalize both dates in a range."""
        return (
            self.normalize_date(start),
            "Present" if self.is_present(end or "") else self.normalize_date(end),
        )

    # ─── Utilities ─────────────────────────────────────────────────────────────
    def is_present(self, text: str) -> bool:
        """Check if text means 'current / present'."""
        return text.strip().lower() in PRESENT_KEYWORDS

    def _try_structured_formats(self, date_str: str) -> Optional[datetime]:
        """Try parsing with a list of known date formats."""
        # Normalize month abbreviations
        normalized = self._normalize_month(date_str)

        all_formats = self.MONTH_YEAR_FORMATS + self.FULL_DATE_FORMATS
        for fmt in all_formats:
            try:
                return datetime.strptime(normalized.strip(), fmt)
            except ValueError:
                continue
        return None

    def _normalize_month(self, text: str) -> str:
        """Expand abbreviated month names."""
        for abbr, full in MONTH_ABBREVIATIONS.items():
            text = re.sub(
                rf"\b{abbr}\.?\b",
                full,
                text,
                flags=re.IGNORECASE,
            )
        return text

    def _find_single_date(self, text: str) -> Optional[str]:
        """Find a single date mention in text."""
        match = patterns.MONTH_YEAR.search(text)
        if match:
            return match.group(0)
        match = patterns.YEAR.search(text)
        if match:
            return match.group(0)
        return None

    def _calculate_duration(
        self,
        start: datetime,
        end: datetime,
    ) -> float:
        """Calculate duration in years between two datetimes."""
        if start > end:
            start, end = end, start
        delta = relativedelta(end, start)
        years = delta.years + delta.months / 12 + delta.days / 365.25
        return round(years, 1)

    def get_total_experience(
        self,
        date_ranges: list[dict],
    ) -> float:
        """
        Calculate total experience years from a list of date ranges.
        Handles overlapping periods by merging them.

        Args:
            date_ranges: List of {"start_datetime": dt, "end_datetime": dt}

        Returns:
            Total years of experience (float)
        """
        intervals = []
        for dr in date_ranges:
            start = dr.get("start_datetime")
            end   = dr.get("end_datetime") or datetime.now()
            if start and end and start <= end:
                intervals.append((start, end))

        if not intervals:
            return 0.0

        # Merge overlapping intervals
        intervals.sort(key=lambda x: x[0])
        merged = [intervals[0]]

        for start, end in intervals[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))

        # Sum up total duration
        total_days = sum(
            (end - start).days
            for start, end in merged
        )
        return round(total_days / 365.25, 1)


# ─── Singleton ─────────────────────────────────────────────────────────────────
date_parser = DateParser()
