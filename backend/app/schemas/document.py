"""
schemas/document.py

Pydantic request/response contracts for the REST API (case study sections
21-22).
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    invoice = "invoice"
    balance_sheet = "balance_sheet"
    profit_and_loss = "profit_and_loss"
    cash_flow_statement = "cash_flow_statement"


class ProcessingStatus(str, Enum):
    PASS = "PASS"
    FAILED = "FAILED"


class FileValidationResult(BaseModel):
    is_supported_format: bool
    is_readable: bool
    is_within_page_limit: bool
    file_type: Optional[str] = None
    page_count: Optional[int] = None
    file_size_bytes: Optional[int] = None
    errors: List[str] = Field(default_factory=list)


class ValidationCheck(BaseModel):
    name: str
    formula: str
    operands: Dict[str, Any] = Field(default_factory=dict)
    calculated_value: Optional[float] = None
    reported_value: Optional[float] = None
    variance: Optional[float] = None
    tolerance: Optional[float] = None
    status: str  # PASS | FAIL | NOT_APPLICABLE
    period_label: Optional[str] = None
    message: Optional[str] = None


class ValidationSummary(BaseModel):
    checks: List[ValidationCheck] = Field(default_factory=list)
    overall_status: str  # PASS | FAIL | NOT_APPLICABLE
    issues: List[str] = Field(default_factory=list)


class ProcessingMetadata(BaseModel):
    ocr_used: bool = False
    extraction_provider: Optional[str] = None
    processed_at: datetime
    processing_time_ms: int
    pipeline_stage_reached: Optional[str] = None


class ErrorDetail(BaseModel):
    code: str
    message: str


class DocumentProcessResponse(BaseModel):
    document_name: str
    document_type: str
    processing_status: str
    overall_confidence: Optional[float] = None
    file_validation: FileValidationResult
    extracted_data: Optional[Dict[str, Any]] = None
    validation: Optional[ValidationSummary] = None
    processing_metadata: ProcessingMetadata
    error: Optional[ErrorDetail] = None


class DocumentListItem(BaseModel):
    document_name: str
    document_type: str
    processing_status: str
    created_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    total: int
    documents: List[DocumentListItem]


class HealthResponse(BaseModel):
    status: str
    app_name: str
    env: str
    llm_provider: str
    llm_provider_effective: str
    ocr_provider: str
    database_connected: bool
