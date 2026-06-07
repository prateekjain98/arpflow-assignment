# UNFI Remittance Advice Deduction Classification Pipeline

**A FastAPI REST API that automates the classification of deduction line items from UNFI remittance advice documents.**

Upload a batch of PDFs (one RA + noise documents) → the pipeline identifies the RA, extracts every deduction line item, and classifies each into a business category with a structured JSON response.

[![Python](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Tests](https://img.shields.io/badge/Tests-20%2F20%20passing-brightgreen?style=flat-square)](./tests/test_pipeline.py)

---

**📕 Table of Contents**

- [What This Is](#-what-this-is)
- [How It Works](#-how-it-works)
- [Quickstart](#-quickstart)
- [Pipeline Stages](#-pipeline-stages)
- [Category Analysis](#-category-analysis)
- [Handling Document Variation](#-handling-document-variation)
- [When Would an LLM Be Needed?](#-when-would-an-llm-be-needed)
- [API Contract](#-api-contract)
- [Project Structure](#-project-structure)
- [Test Suite](#-test-suite)
- [Technology Stack](#-technology-stack)

---

## 💡 What This Is

When UNFI (United Natural Foods, Inc.) pays a supplier, they frequently pay **less** than the original invoice amount. The shortfall on each line item is called a **deduction**. Deductions come in multiple types — some are legitimate fees, some are disputable claims, and some require backup documentation to resolve.

This pipeline takes a batch of PDF attachments (the RA + noise documents) via a single `POST /classify` endpoint, identifies the remittance advice, extracts every line item, and classifies each deduction into one of six business categories.

> This project was built as a take-home assignment: *"Build a pipeline that identifies the RA, extracts line items, analyzes the pattern reference, proposes categories with justification, and classifies each line item."*

---

## 🔎 How It Works

```
PDF Batch (RA + noise docs)
    │
    ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Document       │───▶│  Line Item      │───▶│  Classification │
│  Identification │    │  Extraction     │    │  Engine         │
│  (hard filters) │    │  (strategy      │    │  (7-family      │
│                 │    │   chain)        │    │   rule engine)  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
   VALID_RA /              invoice_date,            category,
   CORRUPTED_RA /          invoice_number,          subcategory,
   NOISE                   gross_amount,            region,
                           discount_amount,         customer,
                           net_amount               confidence
```

**Pipeline:**

| Stage | What It Does | Output |
|-------|-------------|--------|
| **Identify** | Hard filters (company name + invoice prefixes + structural headers) find exactly one valid RA per batch; noise is ignored | `VALID_RA` / `CORRUPTED_RA` / `NOISE` |
| **Extract** | Strategy chain (pdfplumber tables → pymupdf regex fallback) + date normalization + fused-cell recovery + TOTAL filtering | Structured line items with ISO dates and float amounts |
| **Classify** | 7-family rule engine matches invoice prefixes against documented categories from the reference CSV | `category`, `subcategory`, `region`, `customer`, `confidence` |
| **Summarize** | Aggregates classified items into totals by category | `total_items`, `total_deductions`, `categories` |

---

## 🚀 Quickstart

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
source venv/bin/activate
python -m uvicorn src.main:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`

### Test

```bash
source venv/bin/activate
pytest tests/test_pipeline.py -v
```

### API

```bash
curl -X POST "http://localhost:8000/classify" \
  -F "files=@files/remittance\ advice/256199_01222025_WESTACH.pdf" \
  -F "files=@files/noise/financial_document_1.pdf"
```

---

## 📋 Pipeline Stages

### Stage 1: Document Identification

The pipeline accepts a batch of PDF attachments via `POST /classify`. It uses **hard filters** to identify exactly one valid RA per batch:

| Filter | What It Checks | Why |
|--------|---------------|-----|
| Company name | Contains `"United Natural Foods"` | Confirms this is a UNFI document |
| Invoice prefixes | Contains ≥1 known prefix (`WFM`, `FSR`, `KGFSR`, `ERTT`, `WRTT`, `ERDC`, `WRDC`, `ERNC`, `WRNC`, `MCB`, `YKS`) | Confirms the document has actual deduction data |
| Structural headers | Has `ADVICE DATE`, `ADVICE NUMBER`, tabular data | Confirms the document is a parseable RA |

**Noise handling:** Documents failing the company name or prefix check are classified as `NOISE` and ignored. If multiple documents pass all filters, the pipeline returns HTTP 400. If none pass, it returns HTTP 400.

**Implementation:** `document_identifier.py`

### Stage 2: Line Item Extraction

For the single identified RA, the pipeline extracts every deduction line item using a **strategy chain** that handles structural variation:

**Strategy 1 — pdfplumber table extraction:**
Scans for tables with the header row `INVOICE DATE | INVOICE NUMBER | DESCRIPTION | GROSS AMOUNT | DISCOUNT AMOUNT | NET AMOUNT` and extracts all data rows. This handles the standard 6-column tabular layout.

**Strategy 2 — pymupdf raw text + regex fallback:**
If no tables are found, falls back to line-by-line regex matching. This handles sparse or non-tabular layouts.

**Post-processing:**
- **Date format auto-detection:** If any raw date has day > 12, the document is detected as DD/MM/YY and all dates are parsed consistently. Normalized to ISO format (`YYYY-MM-DD`).
- **Fused-cell recovery:** Merged cells like `04/10/2025\nVENDO` are split using regex.
- **TOTAL row filtering:** Summary rows containing "TOTAL" are excluded from line items.

**Implementation:** `extractor.py`

### Stage 3: Classification

The classifier (`classifier.py`) uses a **7-family rule engine** with exact prefix matching. Given an invoice number, it:

1. **Uppercases and strips** the input
2. **Checks prefix families in order** (longest first to avoid partial matches)
3. **For FSR* invoices:** extracts the customer code after "FSR", looks up the retail partner name (documented codes only)
4. **For WFM* invoices:** strips the 3-letter month code and all digits, matches the remaining suffix against program types
5. **For all others:** direct prefix → category lookup

**Example trace:**
```
WFMAUG2558031ISEWBB
→ WFM family detected
→ Strip WFM → AUG2558031ISEWBB
→ Strip month AUG → 2558031ISEWBB
→ Remove digits → ISEWBB
→ Match ISEWB (longest) → "Whole Foods In-Store Execution Whole Body"
→ Result: Fairshare / Whole Foods In-Store Execution Whole Body / HIGH
```

**Undocumented customer codes:** Three codes (`HAG`, `HAR`, `NSG`) appear in the actual RA data but are not in the reference CSV for Fairshare. They are classified as `Fairshare` (the prefix family is documented) with `customer=null`:

- **`HAG`** — Might be an abbreviation of `HAGGEN` (Row 33, 3rd Party Billing, customer="Haggen"). No `FSRHAG` pattern exists in the reference.
- **`HAR`** — Might be an abbreviation of `HARVES` (Row 35, 3rd Party Billing, customer="Harvest Health Foods") or a variant of `HRT` (Row 185, Fairshare, customer="Harris Teeter"). No `FSRHAR` pattern exists in the reference.
- **`NSG`** — Does not appear anywhere in the reference CSV.

**Confidence:** All 42 invoices in the test data classify as `HIGH` because every prefix is an exact match against a known family. Unknown prefixes return `UNCLASSIFIED` / `NONE`.

**Implementation:** `classifier.py`

### Stage 4: Summary Generation

Builds a summary from classified line items:

```json
{
  "total_items": 30,
  "total_deductions": -46098.89,
  "categories": {"Fairshare": 30}
}
```

**Implementation:** `reporter.py`

---

## 📊 Category Analysis

### How the Reference Was Analyzed

I analyzed all **440 patterns** in the `UNFI deduction pattern reference.csv`. The reference contains 55 granular categories, but a consistent structure emerges:

```
[REGION][PROGRAM][CUSTOMER](date)(remit#)(suffix)
```

Where:
- **REGION** = `E` (East) or `W` (West)
- **PROGRAM** = `FSR`, `WFM`, `TT`, `DC`, `NC`, `MCB`, etc.
- **CUSTOMER** = 2-6 letter retailer abbreviation

**Key finding:** Over 44% of patterns use the `PREFIX(date)(remit#)` structure. The **prefix family** determines the category. Regional splits (ER vs WR) are logistics — they don't change the business purpose.

### Proposed Categories (6)

After analyzing the reference and the actual RA data, I grouped the 55 granular CSV categories into **6 major groups** based on **shared business purpose** and **shared prefix family**:

| # | Category | Prefix Families | Count | % | Justification |
|---|----------|----------------|-------|---|---------------|
| 1 | **Fairshare** | `FSR*`, `WFM*`, `KGFSR*` | 30 | 71% | All represent UNFI's shelf-space equity program. Different prefixes correspond to different retail partners (Whole Foods, Kroger, Sprouts, etc.) but the business purpose is identical: ensuring equal product representation on store shelves. |
| 2 | **Advertising — Quarterly** | `ERDC`, `WRDC` | 4 | 10% | Quarterly advertising catalog participation. ERDC and WRDC are East/West mirrors of the same program. Kept separate from Monthly because Quarterly catalogs are larger, have different lead times, and different pricing structures. |
| 3 | **Advertising — Monthly** | `ERNC`, `WRNC` | 4 | 10% | Natural Connection Flyer — a monthly publication. Different from Quarterly in billing cycle, audience, and publication type. The CSV treats them as distinct programs. |
| 4 | **Food Show** | `ERTT*`, `WRTT*` | 2 | 5% | Table Top trade show participation fees. 19 ERTT/WRTT patterns in the CSV all map to Food Show. The regional split is logistics, not a different program type. These are one-time event fees, not ongoing billing. |
| 5 | **MCB (Customer Specific)** | `MCB*` | 1 | 2% | Manufacturer Charge Back for customer-specific promotional deals. Kept separate from Fairshare because MCB represents **direct promotional agreements** while Fairshare represents **shelf-space equity**. Different business purpose, different dispute handling. |
| 6 | **3rd Party Billing** | `YKS*` | 1 | 2% | Pass-through deductions where UNFI is **not the originator**. The customer (Yokes Specialty) initiated the charge; UNFI merely passes it through. Dispute handling is with the 3rd party, not UNFI. |

#### Why NOT split by customer?

The same retail customer can appear in multiple categories. For example, Harris Teeter appears as:
- `FSRHRT*` → **Fairshare** (shelf space)
- `(invoice#)HRT` → **3rd Party Billing** (pass-through)
- `NSOHRT` → **New Store Opening** (one-time fee)

This proves that **the category is determined by the invoice prefix + business arrangement, not by the customer alone**. Splitting Fairshare by customer would create 20+ categories for the same business purpose, making the taxonomy unusable for the vendor.

**Deep-dive document:** `classification_explanation.md`

---

## 📄 Handling Document Variation

The assignment note states: *"Assume one type of document will not be exactly same, The contents might be same but the structure of the document might differ."*

The extraction layer handles this via a **strategy chain**:

| RA Variant | Structure | Strategy Used | Line Count |
|-----------|-----------|--------------|------------|
| Main RA | Standard 6-column table | pdfplumber table extraction | 30 |
| Small RA | Sparse 6-column table | pdfplumber table extraction | 2 |
| Variant RA | 6-column table with DD/MM/YY dates | pdfplumber table extraction + date auto-detect | 10 |

The fallback to raw text + regex ensures that if pdfplumber fails to find tables (e.g., due to PDF generation differences), the pipeline can still extract line items. No layout-specific templates are required.

---

## 🤖 When Would an LLM Be Needed?

**No LLM or ML model is used in this pipeline.** Classification is purely deterministic rule-based prefix matching.

This is intentional and optimal for the current problem because:

1. **The pattern space is static.** UNFI's invoice prefixes are stable, well-documented in a reference CSV, and change infrequently.
2. **The mapping is unambiguous.** Each prefix family maps to exactly one business category with no overlap or context dependency.
3. **The reference data is authoritative.** The CSV is the ground truth. There is no need for a model to "learn" patterns.

In a real production system, an ML/LLM layer would become necessary if:

| Condition | What Would Replace Rules |
|-----------|------------------------|
| **Dynamic prefixes** | Supervised classifier (XGBoost, embeddings) trained on historical `(invoice_number, category)` pairs |
| **No reference available** | Unsupervised clustering → human labeling → supervised classifier |
| **Semantic descriptions** | LLM fine-tuned on `(description, category)` pairs for natural language understanding |
| **Dispute generation** | LLM downstream for generating dispute letters and explaining classifications in natural language |

---

## 🔌 API Contract

### Request

```bash
curl -X POST "http://localhost:8000/classify" \
  -F "files=@files/remittance\ advice/256199_01222025_WESTACH.pdf" \
  -F "files=@files/noise/financial_document_1.pdf"
```

### Success Response (200)

```json
{
  "ra_document": "256199_01222025_WESTACH.pdf",
  "status": "VALID_RA",
  "total_line_items": 30,
  "classifications": [
    {
      "invoice_date": "2025-09-13",
      "invoice_number": "WFMAUG2558031ISEWBB",
      "gross_amount": -4642.04,
      "discount_amount": 0.0,
      "net_amount": -4642.04,
      "category": "Fairshare",
      "subcategory": "Whole Foods In-Store Execution Whole Body",
      "region": null,
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

| Scenario | Response Body |
|----------|--------------|
| Multiple RAs found | `Multiple valid RA documents found (N). Expected exactly 1 per email batch.` |
| Corrupted RA (missing headers) | `CORRUPTED_RA — missing required headers (ADVICE_DATE, ADVICE_NUMBER). Human review required.` |
| No RA found | `No valid RA document found in batch.` |

---

## 📁 Project Structure

```
.
├── src/
│   ├── main.py                    # FastAPI app + /classify endpoint
│   ├── models.py                  # Pydantic request/response schemas
│   ├── document_identifier.py     # Hard filter logic (RA identification)
│   ├── extractor.py               # Line item extraction (strategy chain)
│   ├── classifier.py              # 7-family rule engine
│   ├── postprocess.py             # Data cleaning (TOTAL row filter)
│   └── reporter.py                # Summary generation
├── tests/
│   └── test_pipeline.py           # Full test suite (20 scenarios)
├── files/
│   ├── remittance advice/         # 3 RA PDF variants
│   ├── noise/                     # 6 unrelated noise documents
│   └── UNFI deduction pattern reference.csv
├── requirements.txt
├── classification_explanation.md  # Deep-dive on classification basis
├── PLAN.md                        # Implementation plan
├── assignment.md                  # Original requirements
└── README.md                      # This file
```

---

## 🧪 Test Suite

20 scenarios covering all requirements and edge cases:

| # | Scenario | Files | Expected |
|---|----------|-------|----------|
| 1 | Happy Path | 1 RA + 1 noise | HTTP 200, 30 classifications |
| 2 | Multiple RAs | 2 RAs + noise | HTTP 400, multiple RAs error |
| 3 | Corrupted RA | Synthetic PDF missing headers | HTTP 400, CORRUPTED_RA |
| 4 | All Noise | 2 noise docs | HTTP 400, no RA found |
| 5–7 | Three Variants | 1 RA each (30, 2, 10 items) | HTTP 200, correct counts |
| 8–10 | RA first, noise second | 1 RA + 1 noise × 3 variants | HTTP 200, correct RA |
| 11–13 | Noise first, RA last | 1 noise + 1 RA × 3 variants | HTTP 200, correct RA |
| 14–16 | RA in middle | 3 noise + 1 RA + 1 noise × 3 variants | HTTP 200, correct RA |
| 17–19 | Random permutation | 1 RA + 5 noise, shuffled × 3 variants | HTTP 200, correct RA |
| 20 | Full noise suite | 1 RA + all 6 noise files, shuffled | HTTP 200, correct RA |

Run:

```bash
pytest tests/test_pipeline.py -v
```

---

## 🛠️ Technology Stack

| Tool | Purpose |
|------|---------|
| `fastapi` | API framework |
| `uvicorn` | ASGI server |
| `python-multipart` | File upload handling |
| `pymupdf` | PDF text extraction (fallback) |
| `pdfplumber` | PDF table extraction (primary) |
| `pytest` | Testing |
| `httpx` | API test client |
