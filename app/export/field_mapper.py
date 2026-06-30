# Map extracted JSON fields → Excel columns
# app/export/field_mapper.py

from typing import Any, Optional

from app.utils.logger import get_logger
from app.utils.helpers import is_empty
from app.models.schemas.extracted_data import ExtractedResumeSchema
from app.models.schemas.export_schema import (
    ExportColumnMapping,
    DEFAULT_COLUMN_MAPPING,
)

logger = get_logger(__name__)


class FieldMapper:
    """
    Maps extracted resume schema fields to flat export rows.

    Responsibilities:
      - Flatten nested schema into a single-level dict
      - Apply column mappings (field_path → column_header)
      - Handle missing fields gracefully with defaults
      - Format values for export (dates, lists, booleans)
      - Support custom column mappings
    """

    def __init__(self):
        pass

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def map_to_row(
        self,
        schema:   ExtractedResumeSchema,
        mapping:  list[ExportColumnMapping] = DEFAULT_COLUMN_MAPPING,
        metadata: Optional[dict]            = None,
    ) -> dict[str, Any]:
        """
        Map a single extracted resume schema to a flat export row.

        Args:
            schema:   Extracted resume schema
            mapping:  Column mapping definitions
            metadata: Optional extra fields (filename, upload_date, etc.)

        Returns:
            Flat dict: {column_header: value}
        """
        # Build flat dict from schema
        flat = schema.to_flat_dict()

        # Add metadata fields if provided
        if metadata:
            flat.update(metadata)

        # Apply column mapping
        row = {}
        for col_map in mapping:
            field_path    = col_map.field_path
            column_header = col_map.column_header
            default       = col_map.default

            # Get value from flat dict
            value = flat.get(field_path, default)

            # Format value for export
            formatted = self._format_value(value, field_path)

            row[column_header] = formatted

        return row

    def map_to_rows(
        self,
        schemas:  list[tuple[ExtractedResumeSchema, Optional[dict]]],
        mapping:  list[ExportColumnMapping] = DEFAULT_COLUMN_MAPPING,
    ) -> list[dict[str, Any]]:
        """
        Map multiple schemas to export rows.

        Args:
            schemas: List of (schema, metadata) tuples
            mapping: Column mapping definitions

        Returns:
            List of flat row dicts
        """
        rows = []
        for schema, metadata in schemas:
            try:
                row = self.map_to_row(schema, mapping, metadata)
                rows.append(row)
            except Exception as e:
                logger.warning(f"Failed to map schema to row: {e}")
                # Add empty row with headers
                rows.append({col.column_header: None for col in mapping})

        logger.info(f"Mapped {len(rows)} schemas to export rows")
        return rows

    # ─── Value Formatting ──────────────────────────────────────────────────────
    def _format_value(
        self,
        value:      Any,
        field_path: str,
    ) -> Any:
        """
        Format a value for export based on its field type.
        """
        if is_empty(value):
            return ""

        # List → comma-separated string
        if isinstance(value, list):
            return self._format_list(value)

        # Float → round to 1 decimal
        if isinstance(value, float):
            return round(value, 1)

        # Boolean → Yes/No
        if isinstance(value, bool):
            return "Yes" if value else "No"

        # String → strip whitespace
        if isinstance(value, str):
            return value.strip()

        return value

    def _format_list(self, items: list) -> str:
        """Format a list as a comma-separated string."""
        if not items:
            return ""
        clean = [str(item).strip() for item in items if item]
        return ", ".join(clean)

    # ─── Flat Dict Builder ─────────────────────────────────────────────────────
    def build_full_flat_dict(
        self,
        schema:   ExtractedResumeSchema,
        metadata: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Build a comprehensive flat dict with ALL available fields.
        Includes nested experience/education as JSON strings.
        """
        import json

        flat = schema.to_flat_dict()

        # Add full nested data as JSON strings
        flat["experience_json"] = json.dumps(
            [e.model_dump() for e in schema.experience],
            default=str,
        )
        flat["education_json"] = json.dumps(
            [e.model_dump() for e in schema.education],
            default=str,
        )
        flat["certifications_json"] = json.dumps(
            [c.model_dump() for c in schema.certifications],
            default=str,
        )
        flat["projects_json"] = json.dumps(
            [p.model_dump() for p in schema.projects],
            default=str,
        )

        # Add metadata
        if metadata:
            flat.update(metadata)

        return flat

    # ─── Column Headers ────────────────────────────────────────────────────────
    def get_headers(
        self,
        mapping: list[ExportColumnMapping] = DEFAULT_COLUMN_MAPPING,
    ) -> list[str]:
        """Return ordered list of column headers."""
        return [col.column_header for col in mapping]

    def get_column_widths(
        self,
        mapping: list[ExportColumnMapping] = DEFAULT_COLUMN_MAPPING,
    ) -> dict[str, int]:
        """Return column header → width mapping."""
        return {
            col.column_header: col.column_width
            for col in mapping
        }

    # ─── Multi-Row Expansion ───────────────────────────────────────────────────
    def expand_experience_rows(
        self,
        schema:   ExtractedResumeSchema,
        metadata: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """
        Expand a single resume into multiple rows — one per job.
        Useful for detailed experience-focused exports.
        """
        if not schema.experience:
            return [self._base_contact_row(schema, metadata)]

        rows = []
        contact = schema.contact

        for exp in schema.experience:
            row = {
                "Full Name":    contact.full_name or "",
                "Email":        contact.email or "",
                "Phone":        contact.phone or "",
                "Job Title":    exp.job_title or "",
                "Company":      exp.company or "",
                "Location":     exp.location or "",
                "Start Date":   exp.start_date or "",
                "End Date":     "Present" if exp.is_current else (exp.end_date or ""),
                "Duration (Yrs)": exp.duration_years or "",
                "Description":  exp.description or "",
                "Responsibilities": self._format_list(exp.responsibilities),
                "All Skills":   self._format_list(schema.skills.all),
            }
            if metadata:
                row.update(metadata)
            rows.append(row)

        return rows

    def expand_education_rows(
        self,
        schema:   ExtractedResumeSchema,
        metadata: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """
        Expand a single resume into multiple rows — one per education entry.
        """
        if not schema.education:
            return [self._base_contact_row(schema, metadata)]

        rows = []
        contact = schema.contact

        for edu in schema.education:
            row = {
                "Full Name":      contact.full_name or "",
                "Email":          contact.email or "",
                "Degree":         edu.degree or "",
                "Field of Study": edu.field_of_study or "",
                "Institution":    edu.institution or "",
                "Location":       edu.location or "",
                "Start Date":     edu.start_date or "",
                "Graduation Date":edu.graduation_date or "",
                "GPA":            edu.gpa or "",
            }
            if metadata:
                row.update(metadata)
            rows.append(row)

        return rows

    def _base_contact_row(
        self,
        schema:   ExtractedResumeSchema,
        metadata: Optional[dict],
    ) -> dict:
        """Build a base row with contact info only."""
        row = {
            "Full Name": schema.contact.full_name or "",
            "Email":     schema.contact.email     or "",
            "Phone":     schema.contact.phone     or "",
        }
        if metadata:
            row.update(metadata)
        return row


# ─── Singleton ─────────────────────────────────────────────────────────────────
field_mapper = FieldMapper()
