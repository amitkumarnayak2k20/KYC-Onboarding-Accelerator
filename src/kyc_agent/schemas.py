from typing import Optional, Literal
from pydantic import BaseModel, Field

DocumentType = Literal["passport", "driving_licence", "national_id", "proof_of_address"]

class ApplicationCreate(BaseModel):
    applicant_id: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    full_name: str = Field(min_length=2, max_length=120)
    email: Optional[str] = Field(default=None, max_length=254)
    application_address: Optional[str] = Field(default=None, max_length=1000)

class DocumentSubmission(BaseModel):
    document_type: DocumentType
    document_text: str = Field(min_length=10, max_length=30000)
    vendor_version: str = Field(default="ocr-v1", max_length=64)
    source_filename: Optional[str] = Field(default=None, max_length=255)

class DocumentRequestCreate(BaseModel):
    document_type: DocumentType
    reason: str = Field(min_length=5, max_length=500)

class ProcessRequest(BaseModel):
    # Backward compatible: document_text supplied here is registered before processing.
    document_type: DocumentType = "passport"
    document_text: Optional[str] = Field(default=None, min_length=10, max_length=30000)
    address_text: Optional[str] = Field(default=None, max_length=1000)
    vendor_version: str = Field(default="ocr-v1", max_length=64)

class ExtractedFields(BaseModel):
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    document_number: Optional[str] = None
    expiry_date: Optional[str] = None
    address: Optional[str] = None
    document_type: Optional[str] = None

class EvaluationRequest(BaseModel):
    sample_ids: Optional[list[str]] = None
