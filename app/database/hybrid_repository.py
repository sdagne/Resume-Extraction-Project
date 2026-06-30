# app/database/hybrid_repository.py
"""
Hybrid Persistence Layer  —  Stage 8 of the extraction pipeline.

Dual-write strategy:
  ┌─ TRACK A: Legacy CRM (best-effort) ────────────────────────────────────┐
  │  Tables:  IAPL_CRM_RESUME_PROFILE                                       │
  │           IAPL_CRM_RESUME_SECTION_ITEM                                  │
  │  Failure: NEVER breaks the main flow — logged as warning only           │
  └─────────────────────────────────────────────────────────────────────────┘
  ┌─ TRACK B: Normalized OCR Schema ───────────────────────────────────────┐
  │  Tables:  Candidates_text_to_ocr                                        │
  │           Educations_text_to_ocr                                        │
  │           Companies_text_to_ocr                                         │
  │           Skills_text_to_ocr                                            │
  │           Languages_text_to_ocr                                         │
  │           Projects_text_to_ocr                                          │
  │           Certifications_text_to_ocr                                    │
  │           Resume_Raw_Data_text_to_ocr                                   │
  └─────────────────────────────────────────────────────────────────────────┘

Both tracks are attempted independently.  A failure in Track B does NOT
prevent Track A from completing, and vice versa.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PersistenceResult:
    """Tracks what was persisted and what failed."""
    legacy_success:     bool = False
    legacy_error:       Optional[str] = None

    normalized_success: bool = False
    normalized_error:   Optional[str] = None

    resume_raw_id:      Optional[str] = None   # PK from Resume_Raw_Data_text_to_ocr

    def as_dict(self) -> dict:
        return {
            "legacy_success":     self.legacy_success,
            "legacy_error":       self.legacy_error,
            "normalized_success": self.normalized_success,
            "normalized_error":   self.normalized_error,
            "resume_raw_id":      self.resume_raw_id,
        }


class HybridRepository:
    """
    Dual-write repository.

    Usage:
        result = hybrid_repo.insert_extraction(
            db          = db_session,
            resume_id   = uuid,
            schema      = extracted_schema,
            raw_text    = full_text,
            file_path   = "/app/uploads/xxx.pdf",
            inserted_by = "api",
        )
    """

    def insert_extraction(
        self,
        db:           Session,
        resume_id:    UUID,
        schema:       Any,
        raw_text:     str        = "",
        file_path:    str        = "",
        inserted_by:  str        = "system",
    ) -> PersistenceResult:
        """
        Persist extracted data via both tracks.

        Track A and Track B are fully independent — failure in one
        does NOT roll back the other.
        """
        result  = PersistenceResult()
        now     = datetime.now(tz=timezone.utc)

        # ── Track A: Legacy CRM ────────────────────────────────────────────────
        try:
            self._insert_legacy(db, resume_id, schema, now)
            result.legacy_success = True
            logger.info(f"Track A (legacy CRM) success | resume_id={resume_id}")
        except Exception as exc:
            db.rollback()
            result.legacy_error = str(exc)
            logger.warning(
                f"Track A (legacy CRM) FAILED (non-fatal) | "
                f"resume_id={resume_id} | error={exc}"
            )

        # ── Track B: Normalized OCR Schema ────────────────────────────────────
        try:
            raw_id = self._insert_normalized(
                db, resume_id, schema, raw_text, file_path, inserted_by, now
            )
            result.normalized_success = True
            result.resume_raw_id      = raw_id
            logger.info(
                f"Track B (normalized OCR) success | resume_id={resume_id} | "
                f"raw_id={raw_id}"
            )
        except Exception as exc:
            db.rollback()
            result.normalized_error = str(exc)
            logger.warning(
                f"Track B (normalized OCR) FAILED (non-fatal) | "
                f"resume_id={resume_id} | error={exc}"
            )

        return result

    # ─── Track A: Legacy CRM ──────────────────────────────────────────────────
    def _insert_legacy(
        self,
        db:        Session,
        resume_id: UUID,
        schema:    Any,
        now:       datetime,
    ) -> None:
        """
        Best-effort insert into legacy IAPL CRM tables.

        These tables are assumed to already exist in the database.
        Schema is kept intentionally minimal — only the fields that
        legacy systems consumed historically.
        """
        contact = getattr(schema, "contact", None)
        name    = getattr(contact, "name",  "") if contact else ""
        email   = getattr(contact, "email", "") if contact else ""
        phone   = getattr(contact, "phone", "") if contact else ""

        # Profile row
        db.execute(
            """
            INSERT INTO "IAPL_CRM_RESUME_PROFILE"
                (resume_id, candidate_name, email, phone, created_at)
            VALUES
                (:rid, :name, :email, :phone, :ts)
            ON CONFLICT (resume_id) DO UPDATE
                SET candidate_name = EXCLUDED.candidate_name,
                    email          = EXCLUDED.email,
                    phone          = EXCLUDED.phone
            """,
            {
                "rid":   str(resume_id),
                "name":  name,
                "email": email,
                "phone": phone,
                "ts":    now,
            },
        )

        # Section items
        sections: dict[str, list] = {
            "experience":     getattr(schema, "experience",     []),
            "education":      getattr(schema, "education",      []),
            "skills":         self._flatten_skills(schema),
            "certifications": getattr(schema, "certifications", []),
        }

        for section_name, items in sections.items():
            for idx, item in enumerate(items):
                db.execute(
                    """
                    INSERT INTO "IAPL_CRM_RESUME_SECTION_ITEM"
                        (resume_id, section_name, item_index,
                         item_text, created_at)
                    VALUES
                        (:rid, :sec, :idx, :text, :ts)
                    ON CONFLICT DO NOTHING
                    """,
                    {
                        "rid":  str(resume_id),
                        "sec":  section_name,
                        "idx":  idx,
                        "text": self._item_to_text(item),
                        "ts":   now,
                    },
                )

        db.commit()

    # ─── Track B: Normalized OCR Tables ──────────────────────────────────────
    def _insert_normalized(
        self,
        db:          Session,
        resume_id:   UUID,
        schema:      Any,
        raw_text:    str,
        file_path:   str,
        inserted_by: str,
        now:         datetime,
    ) -> str:
        """
        Insert into the full normalized *_text_to_ocr table suite.
        Returns the raw_data_id primary key.
        """
        contact = getattr(schema, "contact", None)

        # 1. Candidates_text_to_ocr
        db.execute(
            """
            INSERT INTO "Candidates_text_to_ocr"
                (resume_id, full_name, email, phone, linkedin_url,
                 github_url, portfolio_url, location, headline,
                 file_path, inserted_date, inserted_by)
            VALUES
                (:rid, :name, :email, :phone, :linkedin, :github,
                 :portfolio, :loc, :headline, :fp, :ts, :by)
            ON CONFLICT (resume_id) DO UPDATE
                SET full_name     = EXCLUDED.full_name,
                    email         = EXCLUDED.email,
                    phone         = EXCLUDED.phone,
                    linkedin_url  = EXCLUDED.linkedin_url,
                    github_url    = EXCLUDED.github_url,
                    portfolio_url = EXCLUDED.portfolio_url,
                    inserted_date = EXCLUDED.inserted_date
            """,
            {
                "rid":       str(resume_id),
                "name":      getattr(contact, "name",          "") if contact else "",
                "email":     getattr(contact, "email",         "") if contact else "",
                "phone":     getattr(contact, "phone",         "") if contact else "",
                "linkedin":  getattr(contact, "linkedin_url",  "") if contact else "",
                "github":    getattr(contact, "github_url",    "") if contact else "",
                "portfolio": getattr(contact, "portfolio_url", "") if contact else "",
                "loc":       getattr(contact, "location",      "") if contact else "",
                "headline":  getattr(contact, "headline",      "") if contact else "",
                "fp":        file_path,
                "ts":        now,
                "by":        inserted_by,
            },
        )

        # 2. Educations_text_to_ocr
        for edu in getattr(schema, "education", []):
            db.execute(
                """
                INSERT INTO "Educations_text_to_ocr"
                    (resume_id, institution, degree, field_of_study,
                     start_date, end_date, gpa, raw_text, inserted_date)
                VALUES
                    (:rid, :inst, :deg, :field, :sd, :ed, :gpa, :raw, :ts)
                ON CONFLICT DO NOTHING
                """,
                {
                    "rid":   str(resume_id),
                    "inst":  getattr(edu, "institution",   ""),
                    "deg":   getattr(edu, "degree",        ""),
                    "field": getattr(edu, "field_of_study",""),
                    "sd":    getattr(edu, "start_date",    ""),
                    "ed":    getattr(edu, "end_date",       ""),
                    "gpa":   getattr(edu, "gpa",           None),
                    "raw":   self._item_to_text(edu),
                    "ts":    now,
                },
            )

        # 3. Companies_text_to_ocr  (work experience)
        for exp in getattr(schema, "experience", []):
            db.execute(
                """
                INSERT INTO "Companies_text_to_ocr"
                    (resume_id, company_name, job_title, start_date,
                     end_date, is_current, description, inserted_date)
                VALUES
                    (:rid, :co, :title, :sd, :ed, :curr, :desc, :ts)
                ON CONFLICT DO NOTHING
                """,
                {
                    "rid":   str(resume_id),
                    "co":    getattr(exp, "company",    ""),
                    "title": getattr(exp, "job_title",  ""),
                    "sd":    getattr(exp, "start_date", ""),
                    "ed":    getattr(exp, "end_date",   ""),
                    "curr":  getattr(exp, "is_current", False),
                    "desc":  getattr(exp, "description",""),
                    "ts":    now,
                },
            )

        # 4. Skills_text_to_ocr
        for skill in self._flatten_skills(schema):
            db.execute(
                """
                INSERT INTO "Skills_text_to_ocr"
                    (resume_id, skill_name, inserted_date)
                VALUES (:rid, :sk, :ts)
                ON CONFLICT DO NOTHING
                """,
                {"rid": str(resume_id), "sk": skill, "ts": now},
            )

        # 5. Languages_text_to_ocr
        for lang in getattr(schema, "languages", []):
            db.execute(
                """
                INSERT INTO "Languages_text_to_ocr"
                    (resume_id, language, proficiency, inserted_date)
                VALUES (:rid, :lang, :prof, :ts)
                ON CONFLICT DO NOTHING
                """,
                {
                    "rid":  str(resume_id),
                    "lang": getattr(lang, "name",        str(lang)),
                    "prof": getattr(lang, "proficiency", ""),
                    "ts":   now,
                },
            )

        # 6. Certifications_text_to_ocr
        for cert in getattr(schema, "certifications", []):
            db.execute(
                """
                INSERT INTO "Certifications_text_to_ocr"
                    (resume_id, cert_name, issuer, issue_date,
                     expiry_date, cert_url, inserted_date)
                VALUES
                    (:rid, :name, :issuer, :issue, :expiry, :url, :ts)
                ON CONFLICT DO NOTHING
                """,
                {
                    "rid":    str(resume_id),
                    "name":   getattr(cert, "name",        ""),
                    "issuer": getattr(cert, "issuer",      ""),
                    "issue":  getattr(cert, "issue_date",  ""),
                    "expiry": getattr(cert, "expiry_date", ""),
                    "url":    getattr(cert, "url",         ""),
                    "ts":     now,
                },
            )

        # 7. Resume_Raw_Data_text_to_ocr
        json_data = {}
        try:
            json_data = schema.model_dump() if hasattr(schema, "model_dump") else {}
        except Exception:
            pass

        raw_row = db.execute(
            """
            INSERT INTO "Resume_Raw_Data_text_to_ocr"
                (resume_id, raw_text_resume, json_data,
                 inserted_date, inserted_by)
            VALUES (:rid, :raw, :json, :ts, :by)
            ON CONFLICT (resume_id) DO UPDATE
                SET raw_text_resume = EXCLUDED.raw_text_resume,
                    json_data       = EXCLUDED.json_data,
                    inserted_date   = EXCLUDED.inserted_date
            RETURNING id
            """,
            {
                "rid":  str(resume_id),
                "raw":  raw_text,
                "json": json.dumps(json_data, default=str),
                "ts":   now,
                "by":   inserted_by,
            },
        )

        db.commit()

        row = raw_row.fetchone()
        return str(row[0]) if row else ""

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _flatten_skills(self, schema) -> list[str]:
        skills = getattr(schema, "skills", None)
        if not skills:
            return []
        all_skills = getattr(skills, "all", None)
        if isinstance(all_skills, list):
            return [str(s) for s in all_skills if s]
        return []

    def _item_to_text(self, item: Any) -> str:
        """Serialize a schema item to a short text representation."""
        try:
            if hasattr(item, "model_dump"):
                return json.dumps(item.model_dump(), default=str)
            return str(item)
        except Exception:
            return ""


# ─── Singleton ─────────────────────────────────────────────────────────────────
hybrid_repo = HybridRepository()
