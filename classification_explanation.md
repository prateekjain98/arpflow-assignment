# Classification Basis: Deep Dive

## 1. The Core Problem

When UNFI pays a supplier, they send a Remittance Advice (RA) listing every deduction. Each deduction line has an invoice number like `WFMAUG2558031ISEWBB`. This number is not random — it is a **hierarchical code** where each segment encodes meaning: which retail customer, which program, which region. The supplier cannot understand their deductions without decoding these invoice numbers.

This system decodes them.

---

## 2. How the Reference CSV Was Analyzed

### 2.1 Parsing Multi-Pattern Cells

**11 rows in the CSV contain multiple invoice patterns in a single cell**, separated by line breaks within a quoted field. These are not separate classification rules — they are **variant patterns for the same rule**.

| Row | Patterns | Category | Customer | What They Are |
|-----|----------|----------|----------|---------------|
| 6 | `(invoice #)29CM`, `(invoice#)PCM`, `(invoice#)FNCM` | Recalls — Weights & Measures Fine | — | Three suffix variants for recalled product charges |
| 51 | `(Invoice #)METMKT`, `(Invoice #)MET` | 3rd Party Billing | Metropolitan Market | Abbreviation variants: METMKT and MET are the same customer |
| 181 | `FSRFGE(mmyy)0(Remit #)`, `FSRFGE(mth,yy)0(Remit #)` | Fairshare | Giant Eagle | Date format variants: `mmyy` (AUG25) vs `mth,yy` (AUG,25) |
| 184 | `FSRFLN(mmyy)...`, `FSRFLN(mth,yy)...` | Fairshare | Food Lion | Same: two date format variants |
| 185 | `FSRHAN(mmyy)...`, `FSRHAN(mth,yy)...` | Fairshare | Hannaford | Same: two date format variants |
| 186 | `FSRHRT(mmyy)...`, `FSRHRT(mth,yy)...` | Fairshare | Harris Teeter | Same: two date format variants |
| 187 | `FSRKG(mmyy)...`, `KGFSR(mth,yy)...` | Fairshare | Kroger | **Different prefix order** — FSRKG and KGFSR are the same customer |
| 188 | `FSRPBG(mmyy)...`, `FSRPBG(mth,yy)...` | Fairshare | Publix | Same: two date format variants |
| 195 | `FSRWGM(mmyy)...`, `FSRWGM(mthyy)...` | Fairshare | Wegman's | Same: two date format variants |
| 215 | `LAM(customer invoice #)`, `LAM(customer invoice #)(Supplier Location Code)(Remit #)` | 3rd Party Billing | Lazy Acres | Simple vs extended pattern |
| 337 | `URMP(mthyy)(Remit #)`, `URMP(mth)(Remit #)` | 3rd Party Billing | URM Proposals | Date format variants |

**How this is handled:** Each pattern in a multi-line cell is split into a separate rule. All rules from the same cell share the same category, customer, and description. This gives the classifier multiple matching opportunities without creating conflicting rules.

### 2.2 Structural Patterns Across the CSV

All 440 patterns fall into 8 structural types:

| # | Structure Type | Count | % | Example |
|---|---------------|-------|---|---------|
| 1 | `PREFIX(date)(remit#)` | 138 | 31.4% | `ERDC(mmyy)0(Remit#)` |
| 2 | `(invoice #)SUFFIX` | 115 | 26.2% | `(invoice #)AHOLD` |
| 3 | `STATIC` (no placeholders) | 64 | 14.6% | `NSOHRT` |
| 4 | `PREFIX(date)(remit#)` (extended) | 54 | 12.3% | `CMQ(month)(yy)0(Remit#)` |
| 5 | `PREFIX(invoice#)` | 28 | 6.4% | `BARONS(customer invoice #)` |
| 6 | `PREFIX(other)` | 21 | 4.8% | `LCBC(PO#)` |
| 7 | `DIGIT_PREFIX(date)(remit#)` | 18 | 4.1% | `01ASM(mmddyy)0(Remit#)` |
| 8 | `*WILDCARD` | 2 | 0.5% | `*DM` |

**Key insight:** Over 44% of patterns use the `PREFIX(date)(remit#)` structure. This consistency means the classification logic can rely on **prefix extraction** as the primary mechanism — the prefix family determines the category.

---

## 3. The Consistent Pattern: Prefix Families

After analyzing all 440 patterns, a single consistent structure emerges:

```
[REGION][PROGRAM][CUSTOMER](date)(remit#)(suffix)
```

Where:
- **REGION** = `E` (East) or `W` (West) — optional, determines which UNFI region processes the deduction
- **PROGRAM** = `FSR` (Fairshare), `TT` (Trade Show), `DC` (Deduction/Charge), `NC` (Natural Connection), `MCB` (Manufacturer Charge Back) — determines the deduction family
- **CUSTOMER** = 2-6 letter retailer abbreviation — determines which retail store
- **(date)** = month/year placeholder — timing of the charge
- **(remit#)** = vendor ID — which supplier is being charged
- **(suffix)** = program sub-type — further granularity within a program

### 3.1 Regional Encoding (ER vs WR)

Almost all ER* and WR* prefixes are **mirrors** of each other:

| East Prefix | West Prefix | Category |
|-------------|-------------|----------|
| `ERDC` | `WRDC` | Advertising — Quarterly |
| `ERNC` | `WRNC` | Advertising — Monthly |
| `ERTT` | `WRTT` | Food Show |
| `ERCBP` | `WRCBP` | Advertising — Monthly |
| `ERDWB` | `WRDWB` | Advertising — Monthly |

This mirroring is a **structural invariant** in the CSV. The regional split (East/West) exists within the same category — it does not change the category. This justifies grouping ERDC/WRDC together as "Advertising — Quarterly" rather than splitting them into separate categories.

**Exception:** `WRDCE` ≠ `WRDC`. The extra `E` changes the category from Quarterly to Monthly. This is a genuine sub-program distinction captured in the CSV.

### 3.2 Program Encoding

The middle letters of the prefix encode the program type:

| Code | Meaning | Category |
|------|---------|----------|
| `FSR` | Fairshare | Fairshare |
| `WFM` | Whole Foods Market | Fairshare |
| `TT` | Table Top (Trade Show) | Food Show |
| `DC` | Deduction Charge | Advertising — Quarterly |
| `DCE` | Deduction Charge Extended | Advertising — Monthly |
| `NC` | Natural Connection | Advertising — Monthly |
| `MCB` | Manufacturer Charge Back | MCB |
| `SO` | Special Order / New Store | New Store Opening |
| `OVP` | Overpull | Spoils/Overpull |
| `SLA` | Shipment Late Arrival | Shipment Fees |

---

## 4. Category Boundary Justification

### Why 6 Categories, Not 55

The reference CSV has 55 granular categories. But only **6 major groups** appear in the actual RA data. The justification for grouping is based on **shared business purpose** and **shared prefix family**.

### Category 1: Fairshare (30 items, 71.4%)

**Prefixes:** `WFM*`, `FSR*`, `KGFSR`

**What it is:** UNFI's shelf-space equity program. Suppliers pay a fee to ensure their products get equal representation on store shelves across retail locations. This is a **store-initiated program** — the retail customer (Whole Foods, Kroger, Sprouts) runs their version of the program, and UNFI bills the supplier on their behalf.

**Why grouped together:**
- All 33 FSR* patterns in the CSV (21 unique customers) and 12 WFM patterns share the same business purpose: **ensuring product shelf representation**
- The description in the CSV says: "Fairshare programs were created in an effort to ensure equal representation of all products on store shelves"
- Different prefixes correspond to different retail customers running the same program type
- All are **negative deductions** (money taken from the supplier)

**Why NOT split by customer:** The supplier needs to know "this is a Fairshare charge" at the category level. The customer name (Whole Foods, Kroger) is a subcategory attribute, not a separate category. Splitting by customer would create 20+ separate categories for the same business purpose.

### Category 2: Advertising — Quarterly (4 items, 9.5%)

**Prefixes:** `ERDC`, `WRDC`

**What it is:** Supplier participation in UNFI's **quarterly** advertising catalogs. UNFI publishes print/digital catalogs quarterly, and suppliers are billed for featuring their products.

**Why grouped together:**
- ERDC and WRDC are East/West mirrors of the same program
- Both map to "Advertising — Quarterly Ad Billings" in the CSV
- Different from Monthly because Quarterly catalogs are larger, have different lead times, and different pricing structures
- **Why separate from Monthly:** Quarterly and Monthly represent genuinely different billing cycles and publication types. The CSV keeps them as separate subcategories under "Advertising."

### Category 3: Advertising — Monthly (4 items, 9.5%)

**Prefixes:** `ERNC`, `WRNC`

**What it is:** Supplier participation in UNFI's **monthly** "Natural Connection Flyer" — a smaller, more frequent advertising publication.

**Why grouped together:**
- ERNC and WRNC are East/West mirrors
- Both map to "Advertising — Monthly Ad Billings" + customer "Natural Connection Flyer"
- **Why separate from Quarterly:** Monthly flyers have a different audience, different pricing, and different billing cycles. The CSV treats them as distinct programs.

### Category 4: Food Show (2 items, 4.8%)

**Prefixes:** `ERTT*`, `WRTT*`

**What it is:** Fees for supplier participation in UNFI's "Table Top" trade shows — industry events where suppliers showcase products to retailers.

**Why grouped together:**
- 19 ERTT*/WRTT* patterns in the CSV, all = Food Show
- Regional split (East/West) is logistics, not a different program type
- The sub-types (ORL=Orlando, SSSS=format, etc.) are event locations/formats — they don't change the category
- These are **event fees**, not ongoing billing programs like Advertising or Fairshare

### Category 5: MCB — Manufacturer Charge Back (1 item, 2.4%)

**Prefixes:** `MCB`

**What it is:** A direct promotional deal between the supplier and a specific retail customer. The customer runs an ad or promotion featuring the supplier's product, and the supplier pays them back ("charge back") through UNFI.

**Why separate from Fairshare:**
- MCB represents **direct promotional agreements** ("you promoted my product, I'll pay you back")
- Fairshare represents **shelf-space equity** ("ensure my product is visible")
- Different business purpose, different justification, different dispute handling
- The CSV has 9 MCB patterns split between "Customer Specific" and "Published Promo" — we use the majority (Customer Specific)

### Category 6: 3rd Party Billing (1 item, 2.4%)

**Prefixes:** `YKS`

**What it is:** A **pass-through deduction**. The retail customer (Yokes Specialty) initiated this charge directly. UNFI did not create the fee — they are merely passing the customer's charge through to the supplier.

**Why separate from all others:**
- UNFI is **not the originator** of this charge
- The description in the CSV says: "This is a pass through deduction on behalf of the customer. UNFI passes these through to the supplier"
- Dispute handling is different: the supplier disputes with the 3rd party (Yokes), not with UNFI
- 84 suffix-only patterns in the CSV ((invoice #)XXX) are all 3rd Party Billing — this is a major category with many customers

---

## 5. Same Customer, Different Category: Why Prefix Matters

A critical finding from the CSV: **the same retail customer can appear in multiple categories**. This proves that the category is determined by the **invoice prefix + business arrangement**, not by the customer alone.

| Customer | Fairshare | 3rd Party Billing | New Store Opening | MCB |
|----------|-----------|-------------------|-------------------|-----|
| **Whole Foods** | ISEWB, EDPWB, DCMSWB... | — | — | Pricing Credit |
| **Harris Teeter** | FSRHRT | (invoice#)HRT | NSOHRT | — |
| **Hannaford** | FSRHAN | (invoice#)HAN | NSOHAN | — |
| **Sprouts** | FSRSPR | (invoice#)SPR | — | — |
| **Publix** | FSRPBG | (invoice#)PBG | NSOPBG | — |

**This table proves the classification basis:**
- `FSRHRT(mmyy)...` → **Fairshare** (shelf space program)
- `(invoice#)HRT` → **3rd Party Billing** (pass-through from Harris Teeter)
- `NSOHRT` → **New Store Opening** (one-time fee for new store)

Same customer (Harris Teeter), three different categories, three different invoice prefixes. The prefix determines the category because the prefix encodes the **business arrangement type**, not just the customer.

---

## 6. How the Classification Actually Works

Given an invoice number, the system:

1. **Extracts the alphabetic prefix** (everything before the first digit or placeholder)
2. **Looks up the prefix family** in the 7-family rule table
3. **For FSR* invoices:** extracts the customer code after "FSR", looks up the customer name
4. **For WFM invoices:** strips the month code and digits, matches the remaining suffix against program types
5. **For all others:** direct prefix → category lookup

### Example Trace: `FSRHARFY25Q4058031Y`

**Important context:** The reference CSV documents `FSRHRT` for Harris Teeter Fairshare, but the actual RA data contains `FSRHAR`. `HAR` does not appear in the reference for Fairshare. Two plausible interpretations exist: (a) HAR might be an abbreviation of `HARVES` (Row 35, 3rd Party Billing, customer="Harvest Health Foods"), or (b) HAR might be a variant of `HRT` (Row 185, Fairshare, customer="Harris Teeter"). Because these are hypotheses without direct evidence, the classifier does **not** infer a customer name.

```
Step 1: Extract alphabetic prefix → "FSRHARFY"
Step 2: Strip "FY" suffix → "FSRHAR"
Step 3: Match "FSRHAR" against known FSR customer codes
        "HAR" is not a documented code → no customer match
Step 4: Return: category="Fairshare", customer=null
```

The category is certain because `FSR*` is a documented Fairshare prefix family. The customer name is omitted because `HAR` is not directly documented in the reference CSV.

### Example Trace: `WFMAUG2558031ISEWBB`

```
Step 1: Extract alphabetic prefix → "WFMAUG"
Step 2: Recognize WFM family → Whole Foods
Step 3: Strip "WFM" → "AUG2558031ISEWBB"
Step 4: Strip 3-letter month "AUG" → "2558031ISEWBB"
Step 5: Strip all digits → "ISEWBB"
Step 6: Match "ISEWBB" against WFM program suffixes (longest first)
        ISEWBB starts with "ISEWB" → ISEWB = "In-Store Execution Whole Body"
Step 7: Return: category="Fairshare", subcategory="In-Store Execution Whole Body",
        customer="Whole Foods"
```

---

## 7. Summary

| Aspect | Detail |
|--------|--------|
| **Classification basis** | Invoice number prefix families extracted from reference CSV |
| **Number of families** | 7 prefix families covering all 42 invoices |
| **Number of categories** | 6 major groups (from 55 granular CSV categories) |
| **Multi-pattern handling** | 11 cells split into separate rules, all pointing to same category |
| **Undocumented codes** | 3 FSR prefixes (HAG, HAR, NSG) appear in the actual RA data but are not in the reference CSV. They are classified as Fairshare (correct category) with `customer=null` — no customer name is inferred. |
| **Confidence** | 42/42 invoices classified as HIGH |
| **CSV role** | Design-time analysis only — rules hardcoded, CSV not read at runtime |
