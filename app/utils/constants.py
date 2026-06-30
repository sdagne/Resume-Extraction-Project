# app/utils/constants.py

# ─── Resume Section Names ──────────────────────────────────────────────────────
class SectionName:
    CONTACT        = "contact"
    SUMMARY        = "summary"
    EXPERIENCE     = "experience"
    EDUCATION      = "education"
    SKILLS         = "skills"
    CERTIFICATIONS = "certifications"
    PROJECTS       = "projects"
    LANGUAGES      = "languages"
    AWARDS         = "awards"
    REFERENCES     = "references"
    UNKNOWN        = "unknown"

    ALL = [
        CONTACT, SUMMARY, EXPERIENCE, EDUCATION,
        SKILLS, CERTIFICATIONS, PROJECTS,
        LANGUAGES, AWARDS, REFERENCES,
    ]


# ─── Section Header Keywords ───────────────────────────────────────────────────
SECTION_KEYWORDS = {
    SectionName.CONTACT: [
        "contact", "personal information", "personal details",
        "personal info", "contact details", "contact information",
        "get in touch", "reach me",
    ],
    SectionName.SUMMARY: [
        "summary", "professional summary", "career summary",
        "objective", "career objective", "about me", "profile",
        "professional profile", "overview", "introduction",
    ],
    SectionName.EXPERIENCE: [
        "experience", "work experience", "professional experience",
        "employment", "employment history", "career history",
        "work history", "professional background", "positions held",
        "job history", "relevant experience",
    ],
    SectionName.EDUCATION: [
        "education", "academic background", "academic history",
        "educational background", "qualifications", "academic qualifications",
        "degrees", "schooling", "academic credentials",
    ],
    SectionName.SKILLS: [
        "skills", "technical skills", "core skills", "key skills",
        "competencies", "core competencies", "technologies",
        "technical competencies", "expertise", "tools",
        "tools & technologies", "areas of expertise",
        "professional skills", "soft skills", "hard skills",
    ],
    SectionName.CERTIFICATIONS: [
        "certifications", "certificates", "professional certifications",
        "licenses", "accreditations", "credentials",
        "professional development", "training",
    ],
    SectionName.PROJECTS: [
        "projects", "personal projects", "professional projects",
        "key projects", "notable projects", "portfolio",
        "project experience", "academic projects",
    ],
    SectionName.LANGUAGES: [
        "languages", "language skills", "spoken languages",
        "language proficiency",
    ],
    SectionName.AWARDS: [
        "awards", "honors", "achievements", "accomplishments",
        "recognition", "awards & honors",
    ],
    SectionName.REFERENCES: [
        "references", "referees", "professional references",
    ],
}


# ─── Font Size Thresholds ──────────────────────────────────────────────────────
class FontSize:
    SECTION_HEADER_MIN = 12.0   # Minimum font size to be a section header
    NAME_MIN           = 16.0   # Minimum font size to be a candidate name
    BODY_TEXT_MAX      = 12.0   # Maximum font size for body text


# ─── File Types ────────────────────────────────────────────────────────────────
class FileType:
    PDF  = "pdf"
    DOCX = "docx"
    DOC  = "doc"
    SUPPORTED = [PDF, DOCX, DOC]


# ─── PDF Types ─────────────────────────────────────────────────────────────────
class PDFType:
    DIGITAL = "digital"
    SCANNED = "scanned"
    MIXED   = "mixed"


# ─── Extraction Field Names ────────────────────────────────────────────────────
class FieldName:
    # Contact
    FULL_NAME  = "full_name"
    EMAIL      = "email"
    PHONE      = "phone"
    LINKEDIN   = "linkedin"
    GITHUB     = "github"
    WEBSITE    = "website"
    ADDRESS    = "address"
    CITY       = "city"
    COUNTRY    = "country"

    # Summary
    SUMMARY    = "summary"

    # Experience
    EXPERIENCE = "experience"
    JOB_TITLE  = "job_title"
    COMPANY    = "company"
    START_DATE = "start_date"
    END_DATE   = "end_date"
    DURATION   = "duration"
    DESCRIPTION= "description"
    IS_CURRENT = "is_current"

    # Education
    EDUCATION       = "education"
    DEGREE          = "degree"
    INSTITUTION     = "institution"
    FIELD_OF_STUDY  = "field_of_study"
    GRADUATION_DATE = "graduation_date"
    GPA             = "gpa"

    # Skills
    SKILLS          = "skills"

    # Certifications
    CERTIFICATIONS  = "certifications"
    CERT_NAME       = "cert_name"
    CERT_ISSUER     = "cert_issuer"
    CERT_DATE       = "cert_date"

    # Projects
    PROJECTS        = "projects"
    PROJECT_NAME    = "project_name"
    PROJECT_TECH    = "technologies"
    PROJECT_DESC    = "project_description"

    # Languages
    LANGUAGES       = "languages"
    LANGUAGE_NAME   = "language_name"
    PROFICIENCY     = "proficiency"


# ─── Confidence Levels ─────────────────────────────────────────────────────────
class Confidence:
    HIGH   = "high"    # > 0.85
    MEDIUM = "medium"  # 0.60 – 0.85
    LOW    = "low"     # < 0.60

    HIGH_THRESHOLD   = 0.85
    MEDIUM_THRESHOLD = 0.60


# ─── Export Column Headers ─────────────────────────────────────────────────────
EXCEL_COLUMN_ORDER = [
    "full_name", "email", "phone", "linkedin", "github",
    "address", "city", "country", "summary",
    "total_experience_years", "skills",
    "latest_job_title", "latest_company",
    "education_degree", "education_institution",
    "certifications", "languages",
]


# ─── Date Keywords ─────────────────────────────────────────────────────────────
PRESENT_KEYWORDS = [
    "present", "current", "now", "ongoing",
    "till date", "to date", "today",
]

MONTH_ABBREVIATIONS = {
    "jan": "January", "feb": "February", "mar": "March",
    "apr": "April",   "may": "May",      "jun": "June",
    "jul": "July",    "aug": "August",   "sep": "September",
    "oct": "October", "nov": "November", "dec": "December",
}
