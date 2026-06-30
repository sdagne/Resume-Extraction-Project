# app/utils/regex_patterns.py

import re

# ─── Contact Information ───────────────────────────────────────────────────────
EMAIL = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

PHONE = re.compile(
    r"""
    (?:
        \+?(\d{1,3})            # optional country code
        [\s.\-()]?
    )?
    (?:
        \(?\d{2,4}\)?           # area code
        [\s.\-]?
    )?
    \d{3,4}                     # first segment
    [\s.\-]?
    \d{3,4}                     # second segment
    (?:[\s.\-]?\d{1,4})?        # optional extension
    """,
    re.VERBOSE,
)

LINKEDIN = re.compile(
    r"(?:https?://)?(?:www\.)?linkedin\.com/in/([a-zA-Z0-9\-_%]+)/?",
    re.IGNORECASE,
)

GITHUB = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9\-_%]+)/?",
    re.IGNORECASE,
)

WEBSITE = re.compile(
    r"(?:https?://)?(?:www\.)?([a-zA-Z0-9\-]+\.[a-zA-Z]{2,})(?:/[^\s]*)?",
    re.IGNORECASE,
)

# ─── Dates ─────────────────────────────────────────────────────────────────────
YEAR = re.compile(r"\b(19|20)\d{2}\b")

MONTH_YEAR = re.compile(
    r"""
    \b
    (Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|
     May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|
     Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)
    [\s.,\-/]*
    ((?:19|20)\d{2})
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

DATE_RANGE = re.compile(
    r"""
    (
        (?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|
           May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|
           Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)
        [\s.,\-/]*
        (?:(?:19|20)\d{2})
        |
        (?:(?:19|20)\d{2})
    )
    \s*[-–—to/]+\s*
    (
        (?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|
           May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|
           Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)
        [\s.,\-/]*
        (?:(?:19|20)\d{2})
        |
        (?:(?:19|20)\d{2})
        |
        (?:present|current|now|ongoing|till\s*date|to\s*date|today)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ─── GPA / Grade ───────────────────────────────────────────────────────────────
GPA = re.compile(
    r"""
    (?:GPA|CGPA|Grade|Score)\s*[:\-]?\s*
    (\d+(?:\.\d+)?)\s*(?:/\s*(\d+(?:\.\d+)?))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ─── Section Headers ───────────────────────────────────────────────────────────
SECTION_DIVIDER = re.compile(
    r"^[\s\-_=*#~]{3,}$"  # Lines that are just separators
)

ALL_CAPS_HEADER = re.compile(
    r"^[A-Z][A-Z\s&/\-]{2,}$"  # All-caps text likely a header
)

# ─── Degree Detection ──────────────────────────────────────────────────────────
DEGREE = re.compile(
    r"""
    \b(
        B\.?S\.?|B\.?Sc\.?|Bachelor(?:\s+of\s+Science)?|
        B\.?A\.?|Bachelor(?:\s+of\s+Arts)?|
        B\.?E\.?|B\.?Tech\.?|Bachelor(?:\s+of\s+(?:Engineering|Technology))?|
        M\.?S\.?|M\.?Sc\.?|Master(?:\s+of\s+Science)?|
        M\.?A\.?|Master(?:\s+of\s+Arts)?|
        M\.?B\.?A\.?|Master(?:\s+of\s+Business\s+Administration)?|
        M\.?E\.?|M\.?Tech\.?|Master(?:\s+of\s+(?:Engineering|Technology))?|
        Ph\.?D\.?|Doctor(?:\s+of\s+Philosophy)?|
        Associate(?:\s+of\s+(?:Arts|Science|Applied\s+Science))?|
        Diploma|Certificate|High\s+School|Secondary
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ─── Job Title Seniority ───────────────────────────────────────────────────────
SENIORITY = re.compile(
    r"\b(junior|senior|lead|principal|staff|associate|mid[- ]?level|entry[- ]?level|"
    r"head|director|vp|vice\s+president|chief|manager|intern)\b",
    re.IGNORECASE,
)

# ─── Bullet Points ─────────────────────────────────────────────────────────────
BULLET_POINT = re.compile(
    r"^[\s]*[•●◦‣▸▹►▻\-\*\+>]\s+"
)

# ─── Noise / Cleanup ───────────────────────────────────────────────────────────
MULTIPLE_SPACES   = re.compile(r" {2,}")
MULTIPLE_NEWLINES = re.compile(r"\n{3,}")
NON_ASCII         = re.compile(r"[^\x00-\x7F]+")
CONTROL_CHARS     = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PAGE_NUMBER       = re.compile(r"^\s*(?:page\s*)?\d+\s*(?:of\s*\d+)?\s*$", re.IGNORECASE)
