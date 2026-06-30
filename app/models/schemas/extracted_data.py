# app/models/schemas/extracted_data.py

from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict


# ─── Contact ───────────────────────────────────────────────────────────────────
class ContactSchema(BaseModel):
    full_name:  Optional[str]      = None
    email:      Optional[str]      = None
    phone:      Optional[str]      = None
    linkedin:   Optional[str]      = None
    github:     Optional[str]      = None
    website:    Optional[str]      = None
    address:    Optional[str]      = None
    city:       Optional[str]      = None
    country:    Optional[str]      = None


# ─── Experience ────────────────────────────────────────────────────────────────
class ExperienceItemSchema(BaseModel):
    job_title:      Optional[str]   = None
    company:        Optional[str]   = None
    location:       Optional[str]   = None
    start_date:     Optional[str]   = None
    end_date:       Optional[str]   = None
    duration_years: Optional[float] = None
    is_current:     bool            = False
    description:    Optional[str]   = None
    responsibilities: list[str]     = Field(default_factory=list)


# ─── Education ─────────────────────────────────────────────────────────────────
class EducationItemSchema(BaseModel):
    degree:          Optional[str] = None
    field_of_study:  Optional[str] = None
    institution:     Optional[str] = None
    location:        Optional[str] = None
    start_date:      Optional[str] = None
    graduation_date: Optional[str] = None
    gpa:             Optional[str] = None


# ─── Skills ────────────────────────────────────────────────────────────────────
class SkillsSchema(BaseModel):
    technical:  list[str] = Field(default_factory=list)
    soft:       list[str] = Field(default_factory=list)
    tools:      list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    databases:  list[str] = Field(default_factory=list)
    languages:  list[str] = Field(default_factory=list)   # Programming languages
    all:        list[str] = Field(default_factory=list)   # Flat combined list


# ─── Certification ─────────────────────────────────────────────────────────────
class CertificationItemSchema(BaseModel):
    name:         Optional[str] = None
    issuer:       Optional[str] = None
    date:         Optional[str] = None
    expiry_date:  Optional[str] = None
    credential_id:Optional[str] = None


# ─── Project ───────────────────────────────────────────────────────────────────
class ProjectItemSchema(BaseModel):
    name:          Optional[str] = None
    description:   Optional[str] = None
    technologies:  list[str]     = Field(default_factory=list)
    url:           Optional[str] = None
    start_date:    Optional[str] = None
    end_date:      Optional[str] = None


# ─── Language ──────────────────────────────────────────────────────────────────
class LanguageItemSchema(BaseModel):
    language:    Optional[str] = None
    proficiency: Optional[str] = None   # e.g., 'Native', 'Fluent', 'B2'


# ─── Award ─────────────────────────────────────────────────────────────────────
class AwardItemSchema(BaseModel):
    title:        Optional[str] = None
    issuer:       Optional[str] = None
    date:         Optional[str] = None
    description:  Optional[str] = None


# ─── Confidence Scores ─────────────────────────────────────────────────────────
class FieldConfidenceSchema(BaseModel):
    contact:        Optional[float] = None
    summary:        Optional[float] = None
    experience:     Optional[float] = None
    education:      Optional[float] = None
    skills:         Optional[float] = None
    certifications: Optional[float] = None
    projects:       Optional[float] = None
    languages:      Optional[float] = None
    overall:        Optional[float] = None


# ─── Full Extracted Resume ─────────────────────────────────────────────────────
class ExtractedResumeSchema(BaseModel):
    """
    Complete structured output of a resume extraction.
    This is the main schema stored in Resume.extracted_data (JSONB).
    """
    contact:           ContactSchema                  = Field(default_factory=ContactSchema)
    summary:           Optional[str]                  = None
    experience:        list[ExperienceItemSchema]      = Field(default_factory=list)
    education:         list[EducationItemSchema]       = Field(default_factory=list)
    skills:            SkillsSchema                   = Field(default_factory=SkillsSchema)
    certifications:    list[CertificationItemSchema]   = Field(default_factory=list)
    projects:          list[ProjectItemSchema]         = Field(default_factory=list)
    languages:         list[LanguageItemSchema]        = Field(default_factory=list)
    awards:            list[AwardItemSchema]           = Field(default_factory=list)

    # ─── Metadata ──────────────────────────────────────────────────────────────
    detected_language:     Optional[str]              = None
    total_experience_years:Optional[float]            = None
    sections_detected:     list[str]                  = Field(default_factory=list)
    confidence_scores:     FieldConfidenceSchema      = Field(default_factory=FieldConfidenceSchema)
    extraction_warnings:   list[str]                  = Field(default_factory=list)
    extraction_version:    str                        = "1.0.0"

    model_config = ConfigDict(from_attributes=True)

    def to_flat_dict(self) -> dict:
        """
        Flatten nested schema into a single-level dict for CSV/Excel export.
        """
        exp  = self.experience[0]  if self.experience  else None
        edu  = self.education[0]   if self.education   else None
        cert = self.certifications

        return {
            # Contact
            "full_name":    self.contact.full_name,
            "email":        self.contact.email,
            "phone":        self.contact.phone,
            "linkedin":     self.contact.linkedin,
            "github":       self.contact.github,
            "city":         self.contact.city,
            "country":      self.contact.country,

            # Summary
            "summary":      self.summary,

            # Experience
            "total_experience_years":  self.total_experience_years,
            "latest_job_title":        exp.job_title  if exp else None,
            "latest_company":          exp.company    if exp else None,
            "latest_start_date":       exp.start_date if exp else None,
            "latest_end_date":         exp.end_date   if exp else None,

            # Education
            "highest_degree":          edu.degree          if edu else None,
            "field_of_study":          edu.field_of_study  if edu else None,
            "institution":             edu.institution     if edu else None,
            "graduation_date":         edu.graduation_date if edu else None,

            # Skills
            "all_skills":              ", ".join(self.skills.all),
            "technical_skills":        ", ".join(self.skills.technical),

            # Certifications
            "certifications":          ", ".join(c.name for c in cert if c.name),

            # Languages
            "spoken_languages":        ", ".join(
                f"{l.language} ({l.proficiency})" if l.proficiency else l.language
                for l in self.languages if l.language
            ),

            # Confidence
            "overall_confidence":      self.confidence_scores.overall,
        }
