"""Pydantic models for the UNFI RA Classification Pipeline."""

from pydantic import BaseModel
from typing import List, Optional, Dict


class ClassificationResult(BaseModel):
    """Result of classifying a single invoice number."""
    category: str
    subcategory: Optional[str] = None
    region: Optional[str] = None
    customer: Optional[str] = None


class LineItem(BaseModel):
    """A single line item from a remittance advice."""
    invoice_date: Optional[str] = None
    invoice_number: str
    description: Optional[str] = None
    gross_amount: Optional[float] = None
    discount_amount: Optional[float] = None
    net_amount: float
    category: str
    subcategory: Optional[str] = None
    region: Optional[str] = None
    customer: Optional[str] = None


class ClassificationSummary(BaseModel):
    """Summary of a classification batch."""
    total_items: int
    total_deductions: float
    categories: Dict[str, int]


class ClassificationResponse(BaseModel):
    """Response from the /classify endpoint."""
    ra_document: str
    status: str
    total_line_items: int
    classifications: List[LineItem]
    summary: ClassificationSummary
    advice_date: Optional[str] = None
    advice_number: Optional[str] = None
    total_paid: Optional[float] = None


class DocumentCheckResult(BaseModel):
    """Result of checking if a PDF is a valid RA document."""
    filename: str
    is_corrupted: bool = False
    status: str = "NOISE"
    advice_date: Optional[str] = None
    advice_number: Optional[str] = None
    has_advice_date_header: bool = False
    has_advice_number_header: bool = False
    has_tabular_data: bool = False
    has_total_paid: bool = False
