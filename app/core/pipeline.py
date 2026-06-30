# app/core/pipeline.py

import time
from pathlib import Path
from typing import Optional
from uuid import UUID

from app.config import settings
from app.utils.logger import get_logger
from app.utils.constants import PDFType
from app.utils.helpers import generate_uuid

from app.core.pdf_detector   import pdf_detector
from app.core.digital_parser import digital_parser
from app.core.ocr_parser     import ocr_parser
from app.core.layout_analyzer import layout_analyzer
from app.core.column_handler  import column_handler
from app.core.reading_order   import reading_order_reconstructor

from app.extraction.field_extractor  import field_extractor
from app.matching.skills_matcher     import skills_matcher
from app.matching.job_title_normalizer import job_title_normalizer
from app.validation.schema_validator import schema_validator
from app.validation.confidence_scorer import confidence_scorer

from app.models.schemas.extracted_data import ExtractedResumeSchema
from app.storage.temp_manager import temp_manager

# ── Enterprise Tiers ───────────────────────────────────────────────────────────
from app.security.upload_security import upload_security
from app.security.pdf_unlock      import pdf_unlocker, PDFEncryptedError
from app.enhancement.resume_enhancer import resume_enhancer

logger = get_logger(__name__)


class ExtractionPipeline:
    """
    Master pipeline that orchestrates the complete
    resume extraction workflow end-to-end.

    Pipeline stages:
      0.  Security Scan      → magic-byte, JS scan, filename sanitize
      0.5 PDF Unlock         → detect + decrypt password-protected PDFs
      1.  PDF Detection      → digital / scanned / mixed
      2.  Text Extraction    → PyMuPDF or PaddleOCR
      3.  Layout Analysis    → column detection, reading order
      4.  Text Reconstruction→ correct reading order
      5.  Field Extraction   → all resume fields
      6.  Enhancement Layer  → normalize / repair / fuzzy / cert-map / NER
      7.  Skill Matching     → normalize against taxonomy
      8.  Title Normalization→ standardize job titles
      9.  Schema Validation  → validate + sanitize
      10. Confidence Scoring → per-field + overall score
      11. Return Result      → ExtractedResumeSchema
    """

    def __init__(self):
        self.stage_timings: dict[str, float] = {}

    # ─── Main Entry ────────────────────────────────────────────────────────────
    def run(
        self,
        file_path:       str | Path,
        resume_id:       Optional[UUID] = None,
        log_stages:      bool = True,
        file_bytes:      Optional[bytes] = None,
        skip_security:   bool = False,
    ) -> dict:
        """
        Run the complete extraction pipeline on a resume file.

        Args:
            file_path:      Path to the PDF file
            resume_id:      Optional resume ID for logging
            log_stages:     Whether to log timing per stage
            file_bytes:     Raw bytes for security scan (optional but recommended)
            skip_security:  Bypass security scan (testing only)

        Returns:
            {
                "schema":             ExtractedResumeSchema,
                "pdf_metadata":       dict,
                "warnings":           list[str],
                "timings":            dict[str, float],
                "overall_confidence": float,
                "security_report":    dict,
                "enhancement_report": dict,
                "unlock_result":      dict,
            }
        """
        pipeline_start = time.time()
        file_path      = Path(file_path)
        all_warnings   = []

        logger.info(
            f"Pipeline started: {file_path.name} "
            f"(resume_id={resume_id})"
        )

        # ── Stage 0: Security Scan ─────────────────────────────────────────────
        security_report = {}
        if not skip_security and file_bytes is not None:
            sec = self._stage(
                "security_scan",
                lambda: upload_security.assert_upload_safe(
                    file_bytes,
                    file_path.name,
                    max_size_mb=settings.MAX_UPLOAD_SIZE_MB,
                ),
                all_warnings,
            )
            if sec is not None:
                security_report = sec.as_dict()
                if not sec.is_safe:
                    all_warnings.append(
                        f"Security scan failed: {sec.findings}"
                    )
                    logger.error(
                        f"SECURITY: Unsafe file rejected | "
                        f"risk={sec.risk_level} | findings={sec.findings}"
                    )
                    # Return early — do not process malicious files
                    return {
                        "schema":             ExtractedResumeSchema(),
                        "pdf_metadata":       {},
                        "warnings":           all_warnings,
                        "timings":            self.stage_timings,
                        "overall_confidence": 0.0,
                        "security_report":    security_report,
                        "enhancement_report": {},
                        "unlock_result":      {},
                    }

        # ── Stage 0.5: PDF Unlock ──────────────────────────────────────────────
        unlock_info = {}
        try:
            unlock_result = pdf_unlocker.unlock(
                file_path,
                output_dir=settings.TEMP_DIR,
            )
            unlock_info = {
                "was_encrypted": unlock_result.was_encrypted,
                "was_unlocked":  unlock_result.was_unlocked,
                "owner_locked":  unlock_result.owner_locked,
            }
            if unlock_result.was_unlocked and unlock_result.unlocked_path:
                file_path = unlock_result.unlocked_path
                logger.info(
                    f"Using unlocked PDF: {file_path.name} | "
                    f"owner_only={unlock_result.owner_locked}"
                )
        except PDFEncryptedError as exc:
            all_warnings.append(str(exc))
            logger.error(f"PDF unlock failed: {exc}")
            return {
                "schema":             ExtractedResumeSchema(),
                "pdf_metadata":       {},
                "warnings":           all_warnings,
                "timings":            self.stage_timings,
                "overall_confidence": 0.0,
                "security_report":    security_report,
                "enhancement_report": {},
                "unlock_result":      unlock_info,
            }
        except Exception as exc:
            all_warnings.append(f"PDF unlock skipped: {exc}")

        # ── Stage 1: PDF Detection ─────────────────────────────────────────────
        pdf_metadata = self._stage(
            "pdf_detection",
            lambda: pdf_detector.detect(file_path),
            all_warnings,
        )

        pdf_type     = pdf_metadata.get("pdf_type",     PDFType.DIGITAL)
        page_count   = pdf_metadata.get("page_count",   1)
        is_multicolumn = pdf_metadata.get("is_multicolumn", False)
        scanned_pages  = pdf_metadata.get("scanned_pages",  [])
        digital_pages  = pdf_metadata.get("digital_pages",  [])

        logger.info(
            f"PDF type: {pdf_type}, pages: {page_count}, "
            f"multicolumn: {is_multicolumn}"
        )

        # ── Stage 2: Text Extraction ───────────────────────────────────────────
        parse_result = self._run_text_extraction(
            file_path, pdf_type,
            digital_pages, scanned_pages,
            all_warnings,
        )

        text_blocks = parse_result.get("text_blocks", [])
        full_text   = parse_result.get("full_text",   "")

        if not full_text.strip():
            all_warnings.append("No text extracted from document")
            logger.warning("Empty text extraction result")

        # ── Stage 3: Layout Analysis ───────────────────────────────────────────
        page_width  = 595.0   # A4 default
        page_height = 842.0

        if parse_result.get("pages"):
            first_page  = parse_result["pages"][0]
            page_width  = first_page.get("width",  595.0)
            page_height = first_page.get("height", 842.0)

        layout_result = self._stage(
            "layout_analysis",
            lambda: layout_analyzer.analyze(
                text_blocks, page_width, page_height
            ),
            all_warnings,
            default={},
        )

        # ── Stage 4: Text Reconstruction ──────────────────────────────────────
        ordered_blocks = layout_result.get(
            "ordered_blocks", text_blocks
        )

        # Filter noise blocks
        ordered_blocks = reading_order_reconstructor.filter_noise_blocks(
            ordered_blocks
        )

        # Reconstruct text in correct reading order
        if is_multicolumn and layout_result.get("column_boundary"):
            reconstructed_text = self._stage(
                "text_reconstruction",
                lambda: column_handler.reconstruct(
                    ordered_blocks,
                    page_width,
                    layout_result["column_boundary"],
                    layout_result.get("layout_type", "single_column"),
                ),
                all_warnings,
                default=full_text,
            )
        else:
            reconstructed_text = reading_order_reconstructor.reconstruct(
                ordered_blocks
            )

        # Use reconstructed text if better than raw
        final_text = (
            reconstructed_text
            if len(reconstructed_text) >= len(full_text) * 0.5
            else full_text
        )

        # ── Stage 5: Field Extraction ──────────────────────────────────────────
        extracted_schema = self._stage(
            "field_extraction",
            lambda: field_extractor.extract(
                ordered_blocks,
                final_text,
                page_height,
            ),
            all_warnings,
            default=ExtractedResumeSchema(),
        )

        # ── Stage 6: Enhancement Layer ─────────────────────────────────────────
        enhancement_report = {}
        enhanced_schema, enh_report = self._stage(
            "enhancement",
            lambda: resume_enhancer.enhance(extracted_schema, final_text),
            all_warnings,
            default=(extracted_schema, None),
        )
        if enhanced_schema is not None:
            extracted_schema  = enhanced_schema
        if enh_report is not None:
            enhancement_report = {
                "enabled":            enh_report.enabled,
                "passes_run":         enh_report.passes_run,
                "skills_split":       enh_report.skills_split,
                "skills_fuzzy":       enh_report.skills_fuzzy,
                "fields_repaired":    enh_report.fields_repaired,
                "sections_recovered": enh_report.sections_recovered,
                "certs_mapped":       enh_report.certs_mapped,
                "entities_added":     enh_report.entities_added,
            }

        # ── Stage 7: Skill Matching ────────────────────────────────────────────
        extracted_schema = self._stage(
            "skill_matching",
            lambda: self._normalize_skills(extracted_schema),
            all_warnings,
            default=extracted_schema,
        )

        # ── Stage 8: Job Title Normalization ───────────────────────────────────
        extracted_schema = self._stage(
            "title_normalization",
            lambda: self._normalize_titles(extracted_schema),
            all_warnings,
            default=extracted_schema,
        )

        # ── Stage 9: Schema Validation ─────────────────────────────────────────
        validated_schema, validation_warnings = self._stage(
            "schema_validation",
            lambda: schema_validator.validate(extracted_schema),
            all_warnings,
            default=(extracted_schema, []),
        )
        all_warnings.extend(validation_warnings)

        # ── Stage 10: Confidence Scoring ───────────────────────────────────────
        confidence_scores = self._stage(
            "confidence_scoring",
            lambda: confidence_scorer.score(validated_schema),
            all_warnings,
            default={},
        )

        # Update schema confidence scores
        if confidence_scores:
            from app.models.schemas.extracted_data import FieldConfidenceSchema
            validated_schema.confidence_scores = FieldConfidenceSchema(
                contact        = confidence_scores.get("contact"),
                summary        = confidence_scores.get("summary"),
                experience     = confidence_scores.get("experience"),
                education      = confidence_scores.get("education"),
                skills         = confidence_scores.get("skills"),
                certifications = confidence_scores.get("certifications"),
                overall        = confidence_scores.get("overall"),
            )

        # Add pipeline warnings to schema
        validated_schema.extraction_warnings = all_warnings

        # ── Final timing ───────────────────────────────────────────────────────
        total_duration = round(time.time() - pipeline_start, 2)
        self.stage_timings["total"] = total_duration

        overall_confidence = confidence_scores.get("overall", 0.0)

        logger.info(
            f"Pipeline complete: {file_path.name} | "
            f"duration={total_duration}s | "
            f"confidence={overall_confidence:.3f} | "
            f"warnings={len(all_warnings)}"
        )

        return {
            "schema":             validated_schema,
            "pdf_metadata":       pdf_metadata,
            "warnings":           all_warnings,
            "timings":            dict(self.stage_timings),
            "overall_confidence": overall_confidence,
            "security_report":    security_report,
            "enhancement_report": enhancement_report,
            "unlock_result":      unlock_info,
        }

    # ─── Text Extraction Router ────────────────────────────────────────────────
    def _run_text_extraction(
        self,
        file_path:     Path,
        pdf_type:      str,
        digital_pages: list[int],
        scanned_pages: list[int],
        warnings:      list,
    ) -> dict:
        """
        Route to correct parser based on PDF type.
        Handles mixed PDFs by combining both parsers.
        """
        if pdf_type == PDFType.DIGITAL:
            return self._stage(
                "digital_parsing",
                lambda: digital_parser.parse(file_path),
                warnings,
                default={"text_blocks": [], "full_text": "", "pages": []},
            )

        elif pdf_type == PDFType.SCANNED:
            page_images = pdf_detector.get_page_images(file_path, dpi=200)
            return self._stage(
                "ocr_parsing",
                lambda: ocr_parser.parse(file_path, page_images),
                warnings,
                default={"text_blocks": [], "full_text": "", "pages": []},
            )

        elif pdf_type == PDFType.MIXED:
            return self._stage(
                "mixed_parsing",
                lambda: self._parse_mixed(
                    file_path, digital_pages, scanned_pages
                ),
                warnings,
                default={"text_blocks": [], "full_text": "", "pages": []},
            )

        else:
            # Fallback to digital
            return self._stage(
                "fallback_parsing",
                lambda: digital_parser.parse(file_path),
                warnings,
                default={"text_blocks": [], "full_text": "", "pages": []},
            )

    def _parse_mixed(
        self,
        file_path:     Path,
        digital_pages: list[int],
        scanned_pages: list[int],
    ) -> dict:
        """
        Handle mixed PDFs: parse digital pages with PyMuPDF,
        scanned pages with OCR, then merge results.
        """
        # Parse digital pages
        digital_result = digital_parser.parse(file_path)

        # Get images only for scanned pages
        if scanned_pages:
            page_images = pdf_detector.get_page_images(
                file_path,
                page_numbers=scanned_pages,
                dpi=200,
            )
            ocr_result = ocr_parser.parse(file_path, page_images)
        else:
            ocr_result = {"text_blocks": [], "full_text": "", "pages": []}

        # Merge results
        all_blocks = digital_result.get("text_blocks", []) + \
                     ocr_result.get("text_blocks", [])

        # Sort by page number then Y position
        all_blocks.sort(key=lambda b: (
            b.get("page_num", 0),
            b.get("bbox", {}).get("y0", 0),
        ))

        combined_text = (
            digital_result.get("full_text", "") +
            "\n\n" +
            ocr_result.get("full_text", "")
        ).strip()

        return {
            "text_blocks": all_blocks,
            "full_text":   combined_text,
            "pages":       digital_result.get("pages", []) +
                           ocr_result.get("pages", []),
            "tables":      digital_result.get("tables", []) +
                           ocr_result.get("tables", []),
        }

    # ─── Skill Normalization ───────────────────────────────────────────────────
    def _normalize_skills(
        self,
        schema: ExtractedResumeSchema,
    ) -> ExtractedResumeSchema:
        """Normalize extracted skills against taxonomy."""
        if not schema.skills.all:
            return schema

        # Match and normalize all skills
        normalized = skills_matcher.match_and_normalize(schema.skills.all)

        if normalized:
            schema.skills.all = normalized

            # Re-categorize normalized skills
            grouped = skills_matcher.group_related_skills(normalized)
            if grouped.get("frontend") or grouped.get("backend"):
                schema.skills.frameworks = list(set(
                    schema.skills.frameworks +
                    grouped.get("frontend", []) +
                    grouped.get("backend", [])
                ))

        return schema

    # ─── Title Normalization ───────────────────────────────────────────────────
    def _normalize_titles(
        self,
        schema: ExtractedResumeSchema,
    ) -> ExtractedResumeSchema:
        """Normalize job titles in experience entries."""
        for exp in schema.experience:
            if exp.job_title:
                norm_result = job_title_normalizer.normalize(exp.job_title)
                if norm_result["confidence"] >= 0.65:
                    exp.job_title = norm_result["normalized"]

        return schema

    # ─── Stage Runner ──────────────────────────────────────────────────────────
    def _stage(
        self,
        stage_name: str,
        fn,
        warnings:   list,
        default=None,
    ):
        """
        Run a pipeline stage with timing and error handling.
        """
        start = time.time()
        try:
            result = fn()
            duration = round(time.time() - start, 3)
            self.stage_timings[stage_name] = duration
            logger.debug(f"Stage '{stage_name}' completed in {duration}s")
            return result
        except Exception as e:
            duration = round(time.time() - start, 3)
            self.stage_timings[stage_name] = duration
            msg = f"Stage '{stage_name}' failed after {duration}s: {str(e)}"
            logger.error(msg)
            warnings.append(msg)
            return default

    # ─── Quick Extract ─────────────────────────────────────────────────────────
    def quick_extract(
        self,
        file_path: str | Path,
    ) -> ExtractedResumeSchema:
        """
        Quick extraction — returns schema only, no metadata.
        """
        result = self.run(file_path)
        return result["schema"]


# ─── Singleton ─────────────────────────────────────────────────────────────────
extraction_pipeline = ExtractionPipeline()
