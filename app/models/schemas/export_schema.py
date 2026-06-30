# Schema for Excel/CSV export mapping
# app/models/schemas/export_schema.py

from typing import Optional
from pydantic import BaseModel


class ExportColumnMapping(BaseModel):
    """Defines how an extracted field maps to an Excel/CSV column."""
    field_path:   str              # Dot-notation path in ExtractedResumeSchema
    column_header:str              # Display name in Excel/CSV
    column_width: int   = 20       # Excel column width
    is_required:  bool  = False
    default:      Optional[str] = None


# ─── Default Column Mapping ────────────────────────────────────────────────────
DEFAULT_COLUMN_MAPPING: list[ExportColumnMapping] = [
    ExportColumnMapping(field_path="full_name",               column_header="Full Name",               column_width=25, is_required=True),
    ExportColumnMapping(field_path="email",                   column_header="Email",                   column_width=30),
    ExportColumnMapping(field_path="phone",                   column_header="Phone",                   column_width=18),
    ExportColumnMapping(field_path="linkedin",                column_header="LinkedIn",                column_width=35),
    ExportColumnMapping(field_path="github",                  column_header="GitHub",                  column_width=30),
    ExportColumnMapping(field_path="city",                    column_header="City",                    column_width=20),
    ExportColumnMapping(field_path="country",                 column_header="Country",                 column_width=20),
    ExportColumnMapping(field_path="summary",                 column_header="Summary",                 column_width=50),
    ExportColumnMapping(field_path="total_experience_years",  column_header="Total Experience (Years)",column_width=22),
    ExportColumnMapping(field_path="latest_job_title",        column_header="Latest Job Title",        column_width=30),
    ExportColumnMapping(field_path="latest_company",          column_header="Latest Company",          column_width=30),
    ExportColumnMapping(field_path="latest_start_date",       column_header="Start Date",              column_width=15),
    ExportColumnMapping(field_path="latest_end_date",         column_header="End Date",                column_width=15),
    ExportColumnMapping(field_path="highest_degree",          column_header="Highest Degree",          column_width=25),
    ExportColumnMapping(field_path="field_of_study",          column_header="Field of Study",          column_width=25),
    ExportColumnMapping(field_path="institution",             column_header="Institution",             column_width=30),
    ExportColumnMapping(field_path="graduation_date",         column_header="Graduation Date",         column_width=18),
    ExportColumnMapping(field_path="all_skills",              column_header="All Skills",              column_width=60),
    ExportColumnMapping(field_path="technical_skills",        column_header="Technical Skills",        column_width=50),
    ExportColumnMapping(field_path="certifications",          column_header="Certifications",          column_width=40),
    ExportColumnMapping(field_path="spoken_languages",        column_header="Spoken Languages",        column_width=30),
    ExportColumnMapping(field_path="overall_confidence",      column_header="Extraction Confidence",   column_width=22),
]
