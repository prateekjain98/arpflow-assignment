# UNFI Remittance Advice Deduction Classification Pipeline

## What This Is

A FastAPI REST API that automates the classification of deduction line items from UNFI (United Natural Foods, Inc.) remittance advice documents.

When UNFI pays a supplier, they frequently pay less than the original invoice amount. The shortfall on each line item is called a **deduction**. Deductions come in multiple types — some are legitimate fees, some are disputable claims, and some require backup documentation to resolve. This pipeline identifies the type of each deduction automatically.

---

## Assignment Requirements — How Each Is Addressed

### 1. Identify the remittance advice from the document set

The pipeline accepts a batch of PDF attachments (the RA + noise documents) via `POST /classify`. It uses **hard filters** to identify exactly one valid RA per batch:

| Filter | What It Checks | Why |
|--------|---------------|-----|
| Company name | Contains `"United Natural Foods"` | Confirms this is a UNFI document |
| Invoice prefixes | Contains ≥1 known prefix (`WFM`, `FSR`, `KGFSR`, `ERTT`, `WRTT`, `ERDC`, `WRDC`, `ERNC`, `WRNC`, `MCB`, `YKS`) | Confirms the document has actual deduction data |
| Structural headers | Has `ADVICE DATE`, `ADVICE NUMBER`, tabular data | Confirms the document is a parseable RA |

**Noise handling:** Documents failing the company name or prefix check are classified as `NOISE` and ignored. If multiple documents pass all filters, the pipeline returns HTTP 400 ("Multiple valid RA documents found"). If none pass, it returns HTTP 400 ("No valid RA document found").

**Implementation:** `document_identifier.py`

---

### 2. Extract structured line items from it

For the single identified RA, the pipeline extracts every deduction line item using a **strategy chain** that handles structural variation:

**Strategy 1 — pdfplumber table extraction:**
Scans for tables with the header row `INVOICE DATE | INVOICE NUMBER | DESCRIPTION | GROSS AMOUNT | DISCOUNT AMOUNT | NET AMOUNT` and extracts all data rows. This handles the standard 6-column tabular layout.

**Strategy 2 — pymupdf raw text + regex fallback:**
If no tables are found, falls back to line-by-line regex matching. This handles sparse or non-tabular layouts.

**Post-processing:**
- **Date format auto-detection:** If any raw date has day > 12, the document is detected as DD/MM/YY and all dates are parsed consistently. Normalized to ISO format (`YYYY-MM-DD`).
- **Fused-cell recovery:** Merged cells like `04/10/2025
VENDO` are split using regex.
- **TOTAL row filtering:** Summary rows containing "TOTAL" are excluded from line items.

**Extracted fields per line item:**
- `invoice_date`
- `invoice_number`
- `description`
- `gross_amount`
- `discount_amount`
- `net_amount`

**Implementation:** `extractor.py`

---

### 3. Analyze the data and the pattern reference to propose a set of deduction categories — justify why you drew the boundaries where you did

#### Analysis Method

I analyzed all **440 patterns** in the `UNFI deduction pattern reference.csv`. The reference contains 55 granular categories, but a consistent structure emerges:

```
[REGION][PROGRAM][CUSTOMER](date)(remit#)(suffix)
```

Where:
- **REGION** = `E` (East) or `W` (West)
- **PROGRAM** = `FSR`, `WFM`, `TT`, `DC`, `NC`, `MCB`, etc.
- **CUSTOMER** = 2-6 letter retailer abbreviation

**Key finding:** Over 44% of patterns use the `PREFIX(date)(remit#)` structure. The **prefix family** determines the category. Regional splits (ER vs WR) are logistics — they don't change the business purpose.

#### Proposed Categories (6)

After analyzing the reference and the actual RA data, I grouped the 55 granular CSV categories into **6 major groups** based on **shared business purpose** and **shared prefix family**:

| # | Category | Prefix Families | Count | % | Justification |
|---|----------|----------------|-------|---|---------------|
| 1 | **Fairshare** | `FSR*`, `WFM*`, `KGFSR*` | 30 | 71% | All represent UNFI's shelf-space equity program. Different prefixes correspond to different retail partners (Whole Foods, Kroger, Sprouts, etc.) but the business purpose is identical: ensuring equal product representation on store shelves. The CSV explicitly states: "Fairshare programs were created in an effort to ensure equal representation of all products on store shelves." |
| 2 | **Advertising — Quarterly** | `ERDC`, `WRDC` | 4 | 10% | Quarterly advertising catalog participation. ERDC and WRDC are East/West mirrors of the same program. Kept separate from Monthly because Quarterly catalogs are larger, have different lead times, and different pricing structures. |
| 3 | **Advertising — Monthly** | `ERNC`, `WRNC` | 4 | 10% | Natural Connection Flyer — a monthly publication. Different from Quarterly in billing cycle, audience, and publication type. The CSV treats them as distinct programs. |
| 4 | **Food Show** | `ERTT*`, `WRTT*` | 2 | 5% | Table Top trade show participation fees. 19 ERTT/WRTT patterns in the CSV all map to Food Show. The regional split is logistics, not a different program type. These are one-time event fees, not ongoing billing. |
| 5 | **MCB (Customer Specific)** | `MCB*` | 1 | 2% | Manufacturer Charge Back for customer-specific promotional deals. Kept separate from Fairshare because MCB represents **direct promotional agreements** ("you promoted my product, I'll pay you back") while Fairshare represents **shelf-space equity** ("ensure my product is visible"). Different business purpose, different dispute handling. |
| 6 | **3rd Party Billing** | `YKS*` | 1 | 2% | Pass-through deductions where UNFI is **not the originator**. The customer (Yokes Specialty) initiated the charge; UNFI merely passes it through. Dispute handling is with the 3rd party, not UNFI. The CSV describes 84 suffix-only patterns as 3rd Party Billing. |

#### Why NOT split by customer?

The same retail customer can appear in multiple categories. For example, Harris Teeter appears as:
- `FSRHRT*` → **Fairshare** (shelf space)
- `(invoice#)HRT` → **3rd Party Billing** (pass-through)
- `NSOHRT` → **New Store Opening** (one-time fee)

This proves that **the category is determined by the invoice prefix + business arrangement, not by the customer alone**. Splitting Fairshare by customer would create 20+ categories for the same business purpose, making the taxonomy unusable for the vendor.

**Deep-dive document:** `classification_explanation.md`

---

### 4. Classify each line item into one of your proposed categories

The classifier (`classifier.py`) uses a **7-family rule engine** with exact prefix matching. Given an invoice number, it:

1. **Uppercases and strips** the input
2. **Checks prefix families in order** (longest first to avoid partial matches)
3. **For FSR* invoices:** extracts the customer code after "FSR", looks up the retail partner name
4. **For WFM* invoices:** strips the 3-letter month code and all digits, matches the remaining suffix against program types (ISEWB, EDPWB, DCMSWB, etc.)
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

**Confidence:** All 42 invoices in the test data classify as `HIGH` because every prefix is an exact match against a known family. Unknown prefixes return `UNCLASSIFIED` / `NONE`.

**No fuzzy logic is used.** No Levenshtein distance, no regex similarity, no string distance computations. During design-time analysis, some mappings (e.g., `HAR` → Harris Teeter) were inferred from abbreviation patterns in the reference CSV. These inferences were validated and then **hardcoded as exact rules**. The production system never performs inference at runtime.

---

## Pipeline Form & Justification

**Form:** FastAPI REST API (`POST /classify` with multipart file upload)

**Why this form:**
1. **Mimics the real-world input channel** — RAs arrive as email attachments (RA + noise docs). A multipart upload endpoint is the closest digital equivalent.
2. **Built-in file handling** — FastAPI has native multipart/form-data support with automatic `UploadFile` streaming.
3. **Self-documenting** — Automatic Swagger/OpenAPI docs at `/docs` mean anyone can test the API without reading code.
4. **Pydantic validation** — Request/response contracts are validated and typed, preventing malformed outputs.
5. **Industry standard** — FastAPI is the de facto standard for Python APIs; reviewers know how to run and test it immediately.

An alternative like a CLI script would work for batch processing but would require manual file orchestration. A REST API is the natural form for a document-processing pipeline.

---

## Handling Document Structure Variation

The assignment note states: *"Assume one type of document will not be exactly same, The contents might be same but the structure of the document might differ."*

The extraction layer handles this via a **strategy chain**:

| RA Variant | Structure | Strategy Used | Line Count |
|-----------|-----------|--------------|------------|
| Main RA | Standard 6-column table | pdfplumber table extraction | 30 |
| Small RA | Sparse 6-column table | pdfplumber table extraction | 2 |
| Variant RA | 6-column table with DD/MM/YY dates | pdfplumber table extraction + date auto-detect | 10 |

The fallback to raw text + regex ensures that if pdfplumber fails to find tables (e.g., due to PDF generation differences), the pipeline can still extract line items. No layout-specific templates are required.

---

## Why This Pipeline Does Not Use an LLM (And When One Would Be Needed)

**No LLM or ML model is used in this pipeline.** Classification is purely deterministic rule-based prefix matching.

This is intentional and optimal for the current problem because:

1. **The pattern space is static.** UNFI's invoice prefixes (`FSR`, `WFM`, `ERDC`, etc.) are stable, well-documented in a reference CSV, and change infrequently. A hardcoded rule engine is faster, cheaper, and more auditable than any ML model for a fixed lookup problem.
2. **The mapping is unambiguous.** Each prefix family maps to exactly one business category with no overlap or context dependency. There is no nuance or natural language ambiguity to resolve.
3. **The reference data is authoritative.** The CSV is the ground truth. There is no need for a model to "learn" patterns — they are already explicitly stated.

### When an LLM or ML Model Would Become Necessary

In a real production system, an ML/LLM layer would be required if any of the following conditions were true:

#### 1. Dynamic or Evolving Prefix Families
If UNFI introduces new deduction programs quarterly (e.g., `NEWPROGRAM2026XYZ`) without updating the reference CSV, the rule engine would classify every new prefix as `UNCLASSIFIED`. At scale, this creates a maintenance bottleneck.

**What would replace the rule engine:**
A supervised classifier (e.g., XGBoost, Random Forest, or a small neural network) trained on historical `(invoice_number, category)` pairs. The model would learn to generalize from prefix structure — e.g., recognizing that `NEW` + 3-letter customer code + date follows the same structural pattern as `FSR` + customer code + date, and therefore likely belongs to the Fairshare family.

**Why not an LLM here:** A traditional ML model is more appropriate because the input is structured (invoice numbers), the output is categorical, and the decision boundary is based on character-level patterns — not natural language understanding.

#### 2. No Reference Document Available
If the supplier does not have access to UNFI's deduction pattern reference, there is no ground truth to encode as rules. The system would need to **discover** categories from raw data.

**What would replace the rule engine:**
An unsupervised clustering pipeline:
- Extract alphabetic prefixes from all invoice numbers.
- Embed them using TF-IDF or character-level embeddings.
- Cluster using K-Means or DBSCAN.
- A human reviewer labels each cluster ("Cluster A looks like Fairshare, Cluster B looks like Advertising").
- Once labeled, the clusters become a training set for a supervised classifier.

**Where an LLM would help:** An LLM could read the natural language descriptions in the reference CSV (if available) and generate semantic embeddings for each category. Unknown prefixes could then be matched to categories via embedding similarity. However, this still requires the reference document to exist — it just automates the encoding of its knowledge.

#### 3. Semantic Complexity in Descriptions
If the classification depended on the `description` field (which is often empty or generic in RAs) rather than the invoice number, the problem shifts from structured pattern matching to natural language understanding.

**What would replace the rule engine:**
An LLM fine-tuned on historical `(description, category)` pairs. The LLM would read descriptions like "Q3 catalog participation — West region" and classify them as "Advertising — Quarterly" based on semantic understanding.

**Why an LLM is appropriate here:** Natural language descriptions are unstructured, context-dependent, and vary in phrasing. An LLM's ability to understand semantic meaning (not just keyword matching) makes it the right tool for this variant of the problem.

#### 4. Explainability and Dispute Generation
Even with a rule-based classifier, an LLM adds value downstream:
- **Explaining classifications:** "This deduction was classified as Fairshare because the invoice number starts with `FSR`, which corresponds to UNFI's shelf-space equity program for Sprouts."
- **Generating dispute letters:** "We dispute this $4,642.04 Fairshare charge because our contract with Sprouts expired on 2024-12-31, yet this invoice is dated 2025-09-13."

These are natural language generation tasks where an LLM excels, regardless of how the classification itself was performed.

### Summary

| Approach | Best For | Used Here? |
|----------|----------|-----------|
| **Rule-based prefix matching** | Static, known, unambiguous patterns | ✅ Yes |
| **Traditional ML (XGBoost, embeddings)** | Dynamic prefixes, structured data, large scale | ❌ Not needed |
| **Unsupervised clustering** | No reference document, discovering categories | ❌ Not needed |
| **LLM (fine-tuned transformer)** | Semantic descriptions, natural language generation | ❌ Not needed |

The current pipeline uses the right tool for the right problem. If UNFI's prefixes were dynamic and the reference CSV were unavailable, the architecture would shift to an ML classifier for the categorization layer, with an optional LLM for explainability and dispute generation downstream.

---

## Quick Start

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
cd unfi_pipeline
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run the Server

```bash
cd unfi_pipeline
source venv/bin/activate
python -m uvicorn src.main:app --reload --port 8000
```

API docs: `http://localhost:8000/docs`

### Test

```bash
cd unfi_pipeline
source venv/bin/activate
pytest tests/test_pipeline.py -v
```

---

## API Contract

### Request

```bash
curl -X POST "http://localhost:8000/classify" \
  -F "files=@files/remittance\\ advice/256199_01222025_WESTACH.pdf" \
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

## Project Structure

```
.
├── unfi_pipeline/
│   ├── src/
│   │   ├── main.py                    # FastAPI app + /classify endpoint
│   │   ├── models.py                  # Pydantic request/response schemas
│   │   ├── document_identifier.py     # Hard filter logic (RA identification)
│   │   ├── extractor.py               # Line item extraction (strategy chain)
│   │   ├── classifier.py              # 7-family rule engine
│   │   ├── postprocess.py             # Data cleaning (TOTAL row filter)
│   │   └── reporter.py                # Summary generation
│   ├── tests/
│   │   └── test_pipeline.py           # Full test suite (20 scenarios)
│   ├── data/
│   │   └── UNFI deduction pattern reference.csv   # Design-time only
│   └── requirements.txt
├── files/
│   ├── remittance advice/             # 3 RA PDF variants
│   ├── noise/                         # 6 unrelated noise documents
│   └── UNFI deduction pattern reference.csv
├── classification_explanation.md      # Deep-dive on classification basis
├── PLAN.md                            # Implementation plan
├── assignment.md                      # Original requirements
└── README.md                          # This file
```

---

## Test Suite

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

---

## Technology Stack

| Tool | Purpose |
|------|---------|
| `fastapi` | API framework |
| `uvicorn` | ASGI server |
| `python-multipart` | File upload handling |
| `pymupdf` | PDF text extraction (fallback) |
| `pdfplumber` | PDF table extraction (primary) |
| `pytest` | Testing |
| `httpx` | API test client |
