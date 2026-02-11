from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ColumnInput(BaseModel):
    column_name: str = Field(min_length=1)
    data_type: str = ""  # optional for CSV flow (table_name + column_name only)
    nullable: bool = True
    constraints: list[str] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    table_name: str = Field(min_length=1)
    table_context: str | None = None
    columns: list[ColumnInput] = Field(min_length=1)


class ColumnDescription(BaseModel):
    column_name: str
    column_description: str
    business_meaning: str
    pii_flag: bool
    confidence: float = Field(ge=0.0, le=1.0)


class GenerateResponse(BaseModel):
    table_description: str
    columns: list[ColumnDescription]
    model_version: str
    needs_review: bool


class ValidateRequest(BaseModel):
    table_name: str
    generated_payload: GenerateResponse


class ValidationIssue(BaseModel):
    code: str
    message: str
    target: str | None = None


class PiiSummary(BaseModel):
    pii_columns: list[str]
    risk_level: Literal["low", "medium", "high"]


class ValidateResponse(BaseModel):
    valid: bool
    issues: list[ValidationIssue]
    pii_summary: PiiSummary


class ReviewDecision(BaseModel):
    column_name: str
    action: Literal["approved", "edited", "rejected"]
    edited_description: str | None = None


class ReviewRequest(BaseModel):
    table_name: str
    reviewer: str
    decisions: list[ReviewDecision] = Field(min_length=1)
    generated_columns: list[ColumnDescription] = Field(default_factory=list)


class ReviewResponse(BaseModel):
    status: Literal["saved"]
    approved_count: int
    edited_count: int
    rejected_count: int


class ReviewRecord(BaseModel):
    timestamp: datetime
    table_name: str
    reviewer: str
    decisions: list[ReviewDecision]


class DictionaryEntry(BaseModel):
    timestamp: datetime
    table_name: str
    column_name: str
    column_description: str
    business_meaning: str
    pii_flag: bool
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["approved", "edited"]
