# UNFI Remittance Advice Deduction Classification Pipeline

A FastAPI REST API that accepts a batch of PDF attachments (one remittance advice + noise documents), identifies the RA, extracts line items, and classifies each deduction into a business category using a hardcoded rule engine.

## Architecture Choice

**FastAPI** was chosen because:
- Built-in multipart file upload handling (mimics an email attachment webhook).
- Automatic OpenAPI/Swagger documentation.
- Pydantic validation for request/response contracts.
- Industry-standard, async-ready ASGI framework.

## Pipeline Stages

```
POST /classify (multipart/form-data with files[])
│
├─ Stage 1: Document Identification (hard filters)
│   └─ Binary pass/fail on company name + invoice prefixes + structural headers
│
├─ Stage 2: Line Item Extraction (strategy chain)
│   ├─ 1. pdfplumber table extraction
│   ├─ 2. pymupdf raw text + regex fallback
│   └─ Post-processing: date normalization, orphan recovery, fused-cell split
│
├─ Stage 3: Classification (7-family rule engine)
│   └─ Hardcoded rules extracted from reference CSV at design time
│
└─ Stage 4: Summary & Response
    └─ JSON with classifications, totals, and category breakdown
```

## Classification Taxonomy (6 Categories)

| # | Category | Prefix Families | Justification |
|---|----------|----------------|---------------|
| 1 | **Fairshare** | FSR*, WFM*, KGFSR* | UNFI's shelf-space equity program. Different prefixes map to different retail partners (Whole Foods, Kroger, Sprouts, etc.) but the business purpose is identical. |
| 2 | **Advertising — Quarterly** | ERDC, WRDC | Quarterly advertising catalog participation. Separate billing cycle from monthly programs. |
| 3 | **Advertising — Monthly** | ERNC, WRNC | Natural Connection Flyer — a monthly publication. Different from Quarterly in billing cycle and publication type. |
| 4 | **Food Show** | ERTT, WRTT | Table Top trade show participation fees. Regional split (East/West) for event logistics. |
| 5 | **MCB (Customer Specific)** | MCB | Manufacturer Charge Back for customer-specific promotional deals. Kept separate from Fairshare because MCB represents direct promotional agreements while Fairshare represents shelf-space equity. |
| 6 | **3rd Party Billing** | YKS | Pass-through deductions where UNFI is not the originator. The customer initiated the charge; UNFI merely passes it through. |

## Technology Stack

| Tool | Purpose |
|------|---------|
| `fastapi` | API framework |
| `uvicorn` | ASGI server |
| `python-multipart` | File upload handling |
| `pymupdf` | PDF text extraction (fallback) |
| `pdfplumber` | PDF table extraction (primary) |
| `pandas` | Reference CSV analysis (design-time only) |
| `pytest` | Testing |
| `httpx` | API test client |

**No ML. No LLM.** Classification is purely rule-based.

## Running the Server

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python -m uvicorn src.main:app --reload --port 8000
```

The API docs will be available at `http://localhost:8000/docs`.

## API Contract

### Request
```bash
curl -X POST "http://localhost:8000/classify" \
  -F "files=@RA.pdf" \
  -F "files=@noise.pdf"
```

### Success Response (200)
```json
{
  "ra_document": "WESTACH.pdf",
  "status": "VALID_RA",
  "total_line_items": 30,
  "classifications": [
    {
      "invoice_date": "2025-09-13",
      "invoice_number": "WFMAUG2558031ISEWBB",
      "gross_amount": -4642.04,
      "net_amount": -4642.04,
      "category": "Fairshare",
      "subcategory": "Whole Foods In-Store Execution Whole Body",
      "customer": "Whole Foods",
      "confidence": "HIGH"
    }
  ],
  "summary": {
    "total_items": 30,
    "total_deductions": -46098.89,
    "categories": {"Fairshare": 30}
  },
  "advice_date": "01/27/2024",
  "advice_number": "2013326",
  "total_paid": -46098.89
}
```

### Error Responses (400)
- **Multiple RAs**: `"Multiple valid RA documents found (2). Expected exactly 1 per email batch."`
- **Corrupted RA**: `"CORRUPTED_RA — missing required headers (ADVICE_DATE, ADVICE_NUMBER). Human review required."`
- **No RA found**: `"No valid RA document found in batch."`

## Test Suite

```bash
pytest tests/test_pipeline.py -v
```

### Scenarios Covered
1. **Happy Path** — 1 valid RA + noise → HTTP 200, 30 classifications
2. **Multiple RAs** — 2 valid RAs → HTTP 400
3. **Corrupted RA** — Missing headers → HTTP 400 with `CORRUPTED_RA`
4. **All Noise** — No RA in batch → HTTP 400
5. **Three Variants** — Main (30 items), Small (2 items), Variant (10 items) → all HTTP 200

## Design Decisions

### Why hardcoded rules instead of reading the CSV at runtime?
The reference CSV was analyzed **once** at design time to extract the 7 classification families. The resulting rules are encoded as deterministic Python code in `classifier.py`. This means:
- **No runtime CSV dependency** — production system never reads the CSV.
- **Deterministic, auditable behavior** — every classification is traceable to a specific prefix match.
- **Fast execution** — O(1) prefix lookups, no model inference.

### What if the document structure changes?
The extraction layer uses a **strategy chain**: pdfplumber tables first, then regex fallback on raw text. This handles:
- Standard 6-column tables (main RA variant)
- Sparse layouts (small RA variant)
- Merged/fused cells (variant with DD/MM/YY dates)

### No LLM usage
If an LLM API were unavailable, this pipeline would continue to work unchanged. The only place an LLM could add value is in **fuzzy matching** for entirely new invoice prefixes not seen in the reference data. In that case, a fallback would be:
1. Embed the reference descriptions with a lightweight sentence transformer.
2. Use cosine similarity to match unknown prefixes to the nearest known pattern.
3. Flag as `LOW` confidence for human review.
