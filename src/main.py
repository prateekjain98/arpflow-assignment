"""FastAPI application for the UNFI RA Classification Pipeline."""

import io
from typing import List
from fastapi import FastAPI, File, UploadFile, HTTPException

from .models import ClassificationResponse, DocumentCheckResult, LineItem
from .document_identifier import check_document, identify_single_ra
from .extractor import extract_line_items
from .classifier import classify
from .reporter import build_summary
from .postprocess import filter_total_rows

app = FastAPI(
    title="UNFI RA Classification Pipeline",
    description="Automated deduction classification for UNFI remittance advice documents.",
    version="1.0.0",
)


@app.post("/classify", response_model=ClassificationResponse)
async def classify_endpoint(files: List[UploadFile] = File(...)):
    """Accept a batch of PDF attachments and classify deductions from the RA."""

    # --- Stage 1: Document Identification ---
    checked_docs: List[DocumentCheckResult] = []
    file_contents: dict = {}
    for upload in files:
        content = await upload.read()
        file_contents[upload.filename] = content
        result = check_document(io.BytesIO(content), upload.filename)
        checked_docs.append(result)

    try:
        ra_doc = identify_single_ra(checked_docs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # --- Stage 2: Line Item Extraction ---
    ra_bytes = file_contents.get(ra_doc.filename)
    if ra_bytes is None:
        raise HTTPException(status_code=400, detail="Could not re-read RA document.")

    raw_rows, total_paid = extract_line_items(ra_bytes)
    raw_rows = filter_total_rows(raw_rows)

    # --- Stage 3: Classification ---
    classifications: List[LineItem] = []
    for row in raw_rows:
        result = classify(row["invoice_number"])
        classifications.append(
            LineItem(
                invoice_date=row.get("invoice_date"),
                invoice_number=row["invoice_number"],
                description=row.get("description"),
                gross_amount=row.get("gross_amount"),
                discount_amount=row.get("discount_amount"),
                net_amount=row.get("net_amount"),
                category=result.category,
                subcategory=result.subcategory,
                region=result.region,
                customer=result.customer,
                confidence=result.confidence,
            )
        )

    # --- Stage 4: Summary ---
    summary = build_summary(classifications)

    return ClassificationResponse(
        ra_document=ra_doc.filename,
        status=ra_doc.status,
        total_line_items=len(classifications),
        classifications=classifications,
        summary=summary,
        advice_date=ra_doc.advice_date,
        advice_number=ra_doc.advice_number,
        total_paid=total_paid,
    )
