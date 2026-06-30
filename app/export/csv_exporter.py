# app/export/csv_exporter.py

import csv
import io
import json
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

import pandas as pd

from app.config import settings
from app.utils.logger import get_logger
from app.utils.helpers import build_export_filename
from app.models.schemas.extracted_data import ExtractedResumeSchema
from app.models.schemas.export_schema import (
    ExportColumnMapping,
    DEFAULT_COLUMN_MAPPING,
)
from app.export.field_mapper import field_mapper

logger = get_logger(__name__)


class CSVExporter:
    """
    Generates CSV files from extracted resume data.

    Features:
      - Standard CSV export (flat, one row per resume)
      - Detailed CSV (one row per experience entry)
      - In-memory CSV generation (for streaming)
      - Pandas DataFrame integration
      - Multiple encoding support (UTF-8, UTF-8-BOM for Excel compat)
    """

    def __init__(self):
        self.delimiter  = settings.CSV_DELIMITER
        self.encoding   = "utf-8-sig"   # UTF-8 with BOM for Excel compatibility
        self.date_format= settings.EXPORT_DATE_FORMAT

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def export(
        self,
        schemas:     list[tuple[ExtractedResumeSchema, Optional[dict]]],
        output_path: Optional[Path] = None,
        mapping:     list[ExportColumnMapping] = DEFAULT_COLUMN_MAPPING,
        mode:        str = "summary",
    ) -> Path:
        """
        Export multiple resume schemas to a CSV file.

        Args:
            schemas:     List of (schema, metadata) tuples
            output_path: Where to save the file (auto-generated if None)
            mapping:     Column mapping configuration
            mode:        "summary" | "experience" | "education" | "full"

        Returns:
            Path to the generated CSV file
        """
        if output_path is None:
            filename    = build_export_filename(f"resumes_{mode}", "csv")
            output_path = settings.EXPORT_DIR / filename

        logger.info(
            f"Generating CSV export ({mode}): "
            f"{len(schemas)} resumes → {output_path.name}"
        )

        # Build rows based on mode
        if mode == "summary":
            rows    = field_mapper.map_to_rows(schemas, mapping)
            headers = field_mapper.get_headers(mapping)

        elif mode == "experience":
            rows    = []
            headers = [
                "Full Name", "Email", "Job Title", "Company",
                "Location", "Start Date", "End Date",
                "Duration (Yrs)", "Is Current", "Description",
            ]
            for schema, metadata in schemas:
                rows.extend(
                    field_mapper.expand_experience_rows(schema, metadata)
                )

        elif mode == "education":
            rows    = []
            headers = [
                "Full Name", "Email", "Degree", "Field of Study",
                "Institution", "Location", "Start Date",
                "Graduation Date", "GPA",
            ]
            for schema, metadata in schemas:
                rows.extend(
                    field_mapper.expand_education_rows(schema, metadata)
                )

        elif mode == "full":
            rows    = []
            headers = None   # Will be determined from data
            for schema, metadata in schemas:
                flat = field_mapper.build_full_flat_dict(schema, metadata)
                rows.append(flat)
            if rows:
                headers = list(rows[0].keys())

        else:
            raise ValueError(f"Unknown export mode: {mode}")

        # Write CSV
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_csv(rows, headers or [], output_path)

        logger.info(f"CSV export saved: {output_path} ({len(rows)} rows)")
        return output_path

    # ─── CSV Writing ───────────────────────────────────────────────────────────
    def _write_csv(
        self,
        rows:        list[dict[str, Any]],
        headers:     list[str],
        output_path: Path,
    ) -> None:
        """Write rows to a CSV file."""
        if not rows:
            logger.warning("No data to write to CSV")
            # Write empty file with headers only
            with open(output_path, "w", newline="", encoding=self.encoding) as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=headers,
                    delimiter=self.delimiter,
                    extrasaction="ignore",
                )
                writer.writeheader()
            return

        # Use headers from first row if not provided
        if not headers:
            headers = list(rows[0].keys())

        with open(output_path, "w", newline="", encoding=self.encoding) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=headers,
                delimiter=self.delimiter,
                extrasaction="ignore",
                quoting=csv.QUOTE_MINIMAL,
            )
            writer.writeheader()

            for row in rows:
                # Clean values for CSV
                clean_row = {
                    k: self._clean_csv_value(v)
                    for k, v in row.items()
                }
                writer.writerow(clean_row)

    def _clean_csv_value(self, value: Any) -> str:
        """Clean a value for CSV export."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, float):
            return str(round(value, 2))
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    # ─── In-Memory CSV ─────────────────────────────────────────────────────────
    def export_to_string(
        self,
        schemas: list[tuple[ExtractedResumeSchema, Optional[dict]]],
        mapping: list[ExportColumnMapping] = DEFAULT_COLUMN_MAPPING,
    ) -> str:
        """
        Export to CSV string (in memory).
        Useful for streaming responses.
        """
        rows    = field_mapper.map_to_rows(schemas, mapping)
        headers = field_mapper.get_headers(mapping)

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=headers,
            delimiter=self.delimiter,
            extrasaction="ignore",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()

        for row in rows:
            clean_row = {
                k: self._clean_csv_value(v)
                for k, v in row.items()
            }
            writer.writerow(clean_row)

        return output.getvalue()

    def export_to_bytes(
        self,
        schemas: list[tuple[ExtractedResumeSchema, Optional[dict]]],
        mapping: list[ExportColumnMapping] = DEFAULT_COLUMN_MAPPING,
    ) -> bytes:
        """
        Export to CSV bytes (UTF-8-BOM encoded).
        Useful for HTTP response bodies.
        """
        csv_str = self.export_to_string(schemas, mapping)
        return csv_str.encode(self.encoding)

    # ─── Pandas Integration ────────────────────────────────────────────────────
    def to_dataframe(
        self,
        schemas: list[tuple[ExtractedResumeSchema, Optional[dict]]],
        mapping: list[ExportColumnMapping] = DEFAULT_COLUMN_MAPPING,
    ) -> pd.DataFrame:
        """
        Convert extracted schemas to a Pandas DataFrame.
        Useful for further data analysis.
        """
        rows    = field_mapper.map_to_rows(schemas, mapping)
        headers = field_mapper.get_headers(mapping)

        if not rows:
            return pd.DataFrame(columns=headers)

        df = pd.DataFrame(rows, columns=headers)

        # Type conversions
        df = self._optimize_dataframe_types(df)

        logger.info(
            f"DataFrame created: {len(df)} rows × {len(df.columns)} cols"
        )
        return df

    def _optimize_dataframe_types(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optimize DataFrame column types."""
        for col in df.columns:
            col_lower = col.lower()

            # Numeric columns
            if any(k in col_lower for k in ["years", "confidence", "gpa"]):
                df[col] = pd.to_numeric(df[col], errors="coerce")

            # Date columns
            elif any(k in col_lower for k in ["date", "graduation"]):
                # Keep as string (dates are already normalized strings)
                pass

        return df

    def export_from_dataframe(
        self,
        df:          pd.DataFrame,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Export a Pandas DataFrame to CSV."""
        if output_path is None:
            filename    = build_export_filename("dataframe_export", "csv")
            output_path = settings.EXPORT_DIR / filename

        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(
            output_path,
            index=False,
            encoding=self.encoding,
            sep=self.delimiter,
        )
        logger.info(f"DataFrame exported to CSV: {output_path}")
        return output_path

    # ─── Multiple CSV Files ────────────────────────────────────────────────────
    def export_all_modes(
        self,
        schemas:    list[tuple[ExtractedResumeSchema, Optional[dict]]],
        output_dir: Optional[Path] = None,
    ) -> dict[str, Path]:
        """
        Export all modes to separate CSV files.

        Returns:
            Dict of mode → file path
        """
        output_dir = output_dir or settings.EXPORT_DIR
        timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")

        paths = {}
        for mode in ["summary", "experience", "education"]:
            filename   = f"resumes_{mode}_{timestamp}.csv"
            file_path  = output_dir / filename
            paths[mode] = self.export(
                schemas,
                output_path=file_path,
                mode=mode,
            )

        return paths

    # ─── Single Resume Export ──────────────────────────────────────────────────
    def export_single(
        self,
        schema:      ExtractedResumeSchema,
        metadata:    Optional[dict] = None,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Export a single resume to CSV."""
        return self.export(
            schemas     = [(schema, metadata)],
            output_path = output_path,
        )

    def single_to_string(
        self,
        schema:   ExtractedResumeSchema,
        metadata: Optional[dict] = None,
    ) -> str:
        """Export a single resume to CSV string."""
        return self.export_to_string([(schema, metadata)])


# ─── Singleton ─────────────────────────────────────────────────────────────────
csv_exporter = CSVExporter()
