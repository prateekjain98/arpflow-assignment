# Implementation Plan: UNFI Remittance Advice Deduction Classification Pipeline

## Architecture: FastAPI REST API

```
Email with PDF attachments → Webhook → POST /classify (multipart/form-data)
```

**Why FastAPI:** Built-in multipart upload, automatic Swagger docs, Pydantic validation, industry standard.

**Reference CSV:** Design-time input only. Parse it once, extract the business logic, encode it as hardcoded rules. The production system **never touches the CSV at runtime**.

---

## API Contract

```python
POST /classify
Content-Type: multipart/form-data
Body: files[]  # PDF attachments from email (RA + noise documents)

Response 200:
{
  "ra_document": "256199_01222025_WESTACH.pdf",
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
  }
}

Response 400:
{"detail": "Multiple valid RA documents found (2). Expected exactly 1 per email batch. Files: ['WESTACH.pdf', 'WESTACH (1).pdf']"}

Response 400:
{"detail": "CORRUPTED_RA — missing required headers (ADVICE_DATE, ADVICE_NUMBER). Human review required."}

Response 400:
{"detail": "No valid RA document found in batch."}
```

---

## Stage 1: Document Identification — Hard Filters

**No scoring. Binary pass/fail.**

### Minimum Qualifying Conditions (ALL must be true)
| # | Condition | Why |
|---|-----------|-----|
| 1 | Contains `"United Natural Foods"` | Company name — identifies UNFI documents |
| 2 | Contains ≥1 known UNFI invoice prefix | Confirms this is an RA with actual deduction data |

Known prefixes: `WFM`, `FSR`, `KGFSR`, `ERTT`, `WRTT`, `ERDC`, `WRDC`, `ERNC`, `WRNC`, `MCB`, `YKS` (extracted from reference CSV analysis).

### Structural Integrity Check (if qualified)
| # | Check | If Missing |
|---|-------|-----------|
| 3 | Has `ADVICE DATE` header | `CORRUPTED_RA` → human review |
| 4 | Has `ADVICE NUMBER` header | `CORRUPTED_RA` → human review |
| 5 | Has tabular data structure | `CORRUPTED_RA` → human review |
| 6 | Has `TOTAL PAID` summary row | `CORRUPTED_RA` → human review |

### Single RA Enforcement
```python
if len(valid_ras) > 1:
    raise HTTPException(400, 
        "Multiple valid RA documents found (N). "
        "Expected exactly 1 per email batch. "
        "Files: [...]")
```

### Result States
- `VALID_RA` — Conditions 1-6 all pass
- `CORRUPTED_RA` — Conditions 1-2 pass, 3-6 fail → human review required
- `NOISE` — Condition 1 or 2 fails → ignored

---

## Stage 2: Line Item Extraction

**Strategy chain** (try in order, first that produces ≥1 valid row wins):

| Order | Strategy | Library | Best For |
|-------|----------|---------|----------|
| 1 | Table extraction | `pdfplumber` | Standard 6-column tables (main RA) |
| 2 | Raw text + regex | `pymupdf` | 3-column simple layouts (RA variant 2) |
| 3 | Fused-cell recovery | Post-processing | Merged date+invoice (RA variant 3) |

**Post-processing fixes (applied to all strategies):**

1. **Date format detection:** Collect all raw date strings. If any has day > 12 → document uses DD/MM/YY. Parse all dates consistently. Normalize to ISO.

2. **Fused-cell split:** Regex `^(\d{1,2}/\d{1,2}/\d{2,4})\s+([A-Z0-9].*)$` splits merged first column.

3. **TOTAL PAID filter:** Skip row where `invoice_number` contains "TOTAL". Store amount for downstream reporting.

---

## Stage 3: Classification — Business Logic Extracted from Reference

### Core Principle

The reference CSV was analyzed during design to extract classification **patterns**. These patterns are encoded as hardcoded rules in `classifier.py`. The production system **never reads the CSV at runtime**.

### What the Reference Analysis Revealed

After analyzing all 440 rows, the classification logic reduces to **prefix families** with suffix modifiers:

#### Family 1: FSR* → Fairshare (21 patterns in reference, 0 exceptions)

All invoices starting with `FSR` are Fairshare deductions. The next 2-6 letters identify the retail customer.

```python
FSR_CUSTOMERS = {
    "SPR":  "Sprouts",
    "KG":   "Kroger",        # Also appears as KGFSR
    "HRT":  "Harris Teeter",
    "HAR":  "Harris Teeter",  # Data uses HAR abbreviation
    "HAN":  "Hannaford",
    "HAG":  "Haggen",        # Inferred from 3rd Party Billing entry
    "NSG":  "Natural Grocers", # Inferred from 3rd Party Billing entry
    "FGE":  "Giant Eagle",
    "AHOLD": "Stop & Shop",
    "DLHZE": "Delhaize",
    "FLN":  "Food Lion",
    "PBG":  "Publix",
    "SCHNK": "Schnuck's",
    "TFM":  "Fresh Market",
    "WEIS": "Weis",
    "WGM":  "Wegman's",
}

# Classification logic:
# 1. Extract prefix after "FSR" (before digits or "FY")
# 2. Strip "FY" suffix if present (FSRHAGFY25Q4 → FSRHAG)
# 3. Look up customer code in FSR_CUSTOMERS
# 4. Return: category="Fairshare", customer=lookup_result or "Unknown"
```

#### Family 2: WFM* → Fairshare (12 patterns, all Whole Foods)

All `WFM` invoices are Whole Foods Fairshare. The suffix after the vendor ID identifies the program subtype.

```python
WFM_PROGRAMS = {
    "ISEWB": "Whole Foods In-Store Execution Whole Body",
    "ISEGR": "Whole Foods In-Store Execution Grocery",
    "ISE":   "Whole Foods In-Store Execution",
    "EDPWB": "Whole Foods Education Platform Whole Body",
    "EDPGR": "Whole Foods Education Platform Grocery",
    "EDP":   "Whole Foods Education Platform",
    "DCMSWB": "Whole Foods DCMS Whole Body",
    "DCMSGR": "Whole Foods DCMS Grocery",
    "DCMS":  "Whole Foods DCMS",
    "PLANWB": "Whole Foods Audit Whole Body",
    "PLANGR": "Whole Foods Audit Grocery",
    "PLAN":  "Whole Foods Audit",
}

# Classification logic:
# 1. Extract prefix → "WFM"
# 2. Strip 3-letter month code (AUG, SEP, JUL, etc.)
# 3. Strip all digits (invoice number, remittance number, vendor ID)
# 4. Match remaining suffix against WFM_PROGRAMS (longest match first)
# 5. Return: category="Fairshare", subcategory=lookup_result
```

#### Family 3: ERTT* / WRTT* → Food Show (19 patterns)

`ERTT` = East Region, `WRTT` = West Region. Sub-types (ORL, SSSS, SVWE, etc.) identify specific show formats but all map to Food Show.

```python
# Classification logic:
# 1. If starts with "ERTT" → category="Food Show", region="East"
# 2. If starts with "WRTT" → category="Food Show", region="West"
# 3. No customer attribution (internal UNFI event)
```

#### Family 4: ERDC / WRDC → Advertising Quarterly (2 patterns)

```python
# Classification logic:
# 1. If starts with "ERDC" → category="Advertising - Quarterly", region="East"
# 2. If starts with "WRDC" → category="Advertising - Quarterly", region="West"
# 3. NOTE: WRDC ≠ WRDCE (different pattern, different category)
```

#### Family 5: ERNC / WRNC → Advertising Monthly (2 patterns)

```python
# Classification logic:
# 1. If starts with "ERNC" → category="Advertising - Monthly", region="East", customer="Natural Connection"
# 2. If starts with "WRNC" → category="Advertising - Monthly", region="West", customer="Natural Connection"
```

#### Family 6: MCB → Manufacturer Charge Back (9 patterns, 2 subcategories)

```python
# Classification logic:
# 1. If starts with "MCB" → category="MCB (Customer Specific)"
# 2. No further subcategorization from invoice number alone
# 3. The reference shows MCB(yyyymmdd) maps to both Customer Specific (6/9) and Published Promo (3/9)
#    → Use Customer Specific as default (majority)
```

#### Family 7: YKS → 3rd Party Billing (1 pattern)

```python
# Classification logic:
# 1. If starts with "YKS" → category="3rd Party Billing", customer="Yokes Specialty"
```

### Complete Classification Function

```python
def classify(invoice_number: str) -> ClassificationResult:
    inv = invoice_number.upper()
    
    # === FAMILY 1: FSR* → Fairshare ===
    if inv.startswith("FSR"):
        base = inv[3:].split("FY")[0]  # Remove FSR prefix and FY suffix
        # Find longest matching customer code
        for code, customer in sorted(FSR_CUSTOMERS.items(), key=lambda x: -len(x[0])):
            if base.startswith(code):
                return ClassificationResult(
                    category="Fairshare", 
                    subcategory=customer,
                    confidence="HIGH"
                )
        return ClassificationResult(category="Fairshare", confidence="HIGH")
    
    # === FAMILY 2: WFM* → Fairshare ===
    if inv.startswith("WFM"):
        suffix = extract_wfm_suffix(inv)  # Strip WFM, month, digits
        for prog_suffix, program in sorted(WFM_PROGRAMS.items(), key=lambda x: -len(x[0])):
            if suffix.startswith(prog_suffix):
                return ClassificationResult(
                    category="Fairshare",
                    subcategory=program,
                    confidence="HIGH"
                )
        return ClassificationResult(category="Fairshare", confidence="HIGH")
    
    # === FAMILY 3: ERTT*/WRTT* → Food Show ===
    if inv.startswith("ERTT"):
        return ClassificationResult(category="Food Show", region="East", confidence="HIGH")
    if inv.startswith("WRTT"):
        return ClassificationResult(category="Food Show", region="West", confidence="HIGH")
    
    # === FAMILY 4: ERDC/WRDC → Advertising Quarterly ===
    # Exception: WRDCE (with trailing E) is Monthly, not Quarterly.
    if inv.startswith("WRDCE"):
        return ClassificationResult(category="Advertising - Monthly", region="West", confidence="HIGH")
    if inv.startswith("ERDC"):
        return ClassificationResult(category="Advertising - Quarterly", region="East", confidence="HIGH")
    if inv.startswith("WRDC"):
        return ClassificationResult(category="Advertising - Quarterly", region="West", confidence="HIGH")
    
    # === FAMILY 5: ERNC/WRNC → Advertising Monthly ===
    if inv.startswith("ERNC"):
        return ClassificationResult(category="Advertising - Monthly", region="East", customer="Natural Connection", confidence="HIGH")
    if inv.startswith("WRNC"):
        return ClassificationResult(category="Advertising - Monthly", region="West", customer="Natural Connection", confidence="HIGH")
    
    # === FAMILY 6: MCB → Manufacturer Charge Back ===
    if inv.startswith("MCB"):
        return ClassificationResult(category="MCB (Customer Specific)", confidence="HIGH")
    
    # === FAMILY 7: YKS → 3rd Party Billing ===
    if inv.startswith("YKS"):
        return ClassificationResult(category="3rd Party Billing", customer="Yokes Specialty", confidence="HIGH")
    
    # === UNCLASSIFIED ===
    return ClassificationResult(category="UNCLASSIFIED", confidence="NONE")
```

---

## Stage 4: Taxonomy & Justification

### 6 Proposed Categories (extracted from reference analysis)

| # | Category | Items | Justification |
|---|----------|-------|---------------|
| 1 | **Fairshare** | 30 (71%) | All FSR* and WFM* prefixes represent UNFI's shelf-space equity program. Different prefixes correspond to different retail partners (Whole Foods, Kroger, Sprouts, etc.) but the business purpose is identical across all. |
| 2 | **Advertising — Quarterly** | 4 (10%) | ERDC (East) and WRDC (West) represent quarterly advertising catalog participation. Separate billing cycle from monthly programs. |
| 3 | **Advertising — Monthly** | 4 (10%) | ERNC (East) and WRNC (West) represent the Natural Connection Flyer — a monthly publication. Different from Quarterly in billing cycle and publication type. |
| 4 | **Food Show** | 2 (5%) | ERTT (East) and WRTT (West) represent Table Top trade show participation fees. Regional split for event logistics. |
| 5 | **MCB (Customer Specific)** | 1 (2%) | Manufacturer Charge Back for customer-specific promotional deals. Kept separate from Fairshare because MCB represents direct promotional agreements while Fairshare represents shelf-space equity. |
| 6 | **3rd Party Billing** | 1 (2%) | Pass-through deductions where UNFI is not the originator (e.g., Yokes Specialty). The customer initiated the charge; UNFI merely passes it through to the supplier. |

---

## Technology Stack

| Tool | Purpose |
|------|---------|
| `fastapi` | API framework |
| `uvicorn` | ASGI server |
| `python-multipart` | File upload handling |
| `pymupdf` | PDF text extraction |
| `pdfplumber` | PDF table extraction |
| `pandas` | Design-time CSV analysis only (not in requirements.txt) |
| `pytest` | Testing |
| `httpx` | API test client |

No ML. No LLM. Rule-based classification encoded from reference analysis.

---

## Test Suite: 5 Scenarios

### Test 1: Happy Path — 1 Valid RA + Noise
**Input:** `WESTACH.pdf` (30 items) + `financial_document_1.pdf`  
**Expected:** HTTP 200. 1 `VALID_RA`. 30 classifications. Noise ignored.

### Test 2: Multiple RAs — Must Error
**Input:** `WESTACH.pdf` + `WESTACH (1).pdf` + `noise.pdf`  
**Expected:** HTTP 400. "Multiple valid RA documents found (2). Expected exactly 1 per email batch."

### Test 3: Corrupted RA — Missing Headers
**Input:** PDF with "United Natural Foods" + WFM invoices but no `ADVICE DATE`  
**Expected:** HTTP 400. "CORRUPTED_RA — missing required headers. Human review required."

### Test 4: All Noise — No RA Found
**Input:** `lorem_ipsum.pdf` + `sample_accounting_statement.pdf`  
**Expected:** HTTP 400. "No valid RA document found in batch."

### Test 5: Three RA Variants — Independent Processing
**Input:** 3 separate API calls, one per RA variant  
**Expected:** All 3 return HTTP 200 with `VALID_RA`. Line counts: 30, 10, 2.

---

## Project Structure

```
unfi_pipeline/
├── src/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app + /classify endpoint
│   ├── models.py                  # Pydantic request/response models
│   ├── document_identifier.py     # Hard filter logic (conditions 1-6)
│   ├── extractor.py               # Line item extraction + 3 strategies
│   ├── postprocess.py             # Orphan recovery, date detection, TOTAL filter
│   ├── classifier.py              # 7-family rule engine (hardcoded from CSV analysis)
│   └── reporter.py                # Summary generation
├── tests/
│   └── test_pipeline.py           # All 20 test scenarios
├── data/
│   └── UNFI deduction pattern reference.csv    # Design-time only, NOT loaded at runtime
├── requirements.txt
└── README.md
```

---

## Execution Order

```
1. Developer analyzes reference CSV → extracts 7 classification families
2. Developer encodes families as hardcoded rules in classifier.py
3. Server starts → loads classifier.py (no CSV read)
4. POST /classify with PDF attachments
5. Document identification (hard filters, single RA enforcement)
6. Line item extraction (strategy chain + post-processing)
7. Classification (7-family rule engine)
8. Return JSON response
```
