"""Stage 2: Line Item Extraction.

Strategy chain:
  1. pdfplumber table extraction
  2. pymupdf raw text + regex fallback
  3. Fused-cell recovery post-processing
"""

import re
import io
from typing import List, Dict, Any, Optional, Tuple
import pdfplumber
import fitz  # pymupdf


# Regex for parsing a standard 6-column RA line from raw text
LINE_RE = re.compile(
    r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+"
    r"([A-Z0-9]+)\s+"
    r"(.*?)\s+"
    r"([\-\$\d,]+\.\d{2})\s+"
    r"([\-\$\d,]+\.\d{2})\s+"
    r"([\-\$\d,]+\.\d{2})$"
)


def _clean_amount(val: str) -> float:
    """Convert a string like '-$4,642.04' or '$0.00' to float."""
    cleaned = val.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0.0
    return float(cleaned)


def _parse_date(raw: str, day_first: bool = False) -> Optional[str]:
    """Parse a raw date string and return ISO format YYYY-MM-DD."""
    raw = raw.strip().split("\n")[0].split(" ")[0]  # Remove fused text like "2025\nVENDO"
    separators = ["/", "-"]
    sep = None
    for s in separators:
        if s in raw:
            sep = s
            break
    if not sep:
        return None

    parts = raw.split(sep)
    if len(parts) != 3:
        return None

    a, b, c = parts
    a_int, b_int = int(a), int(b)
    year = int(c)
    if year < 100:
        year += 2000

    if day_first:
        day, month = a_int, b_int
    else:
        month, day = a_int, b_int

    # Validate
    if month > 12:
        # Swap if month > 12
        month, day = day, month

    return f"{year:04d}-{month:02d}-{day:02d}"


def _detect_day_first(dates: List[str]) -> bool:
    """If any raw date has day > 12, document uses DD/MM/YY."""
    for d in dates:
        parts = re.split(r"[/-]", d)
        if len(parts) == 3:
            first = int(parts[0])
            if first > 12:
                return True
    return False


def _extract_text_with_pymupdf(file_bytes: bytes) -> str:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return text


def _strategy_pdfplumber(file_bytes: bytes) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    """Try to extract line items using pdfplumber table extraction."""
    rows = []
    total_paid = None

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                # Find header row
                header_idx = None
                for idx, row in enumerate(table):
                    if row and any("INVOICE DATE" in str(cell or "").upper() for cell in row):
                        header_idx = idx
                        break
                if header_idx is None:
                    continue

                for row in table[header_idx + 1 :]:
                    if not row or len(row) < 6:
                        continue
                    # Map cells — pdfplumber may return None for merged cells
                    invoice_date = str(row[0] or "").strip()
                    invoice_number = str(row[1] or "").strip()
                    description = str(row[2] or "").strip()
                    gross = str(row[3] or "").strip()
                    discount = str(row[4] or "").strip()
                    net = str(row[5] or "").strip()

                    if "TOTAL" in invoice_number.upper() or "TOTAL" in (description or "").upper():
                        # Try to capture total paid
                        try:
                            total_paid = _clean_amount(net or gross)
                        except Exception:
                            pass
                        continue

                    if not invoice_number:
                        continue

                    try:
                        rows.append({
                            "invoice_date": invoice_date,
                            "invoice_number": invoice_number,
                            "description": description or None,
                            "gross_amount": _clean_amount(gross) if gross else None,
                            "discount_amount": _clean_amount(discount) if discount else None,
                            "net_amount": _clean_amount(net) if net else None,
                        })
                    except Exception:
                        continue

    return rows, total_paid


def _strategy_regex(text: str) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    """Fallback: parse raw text lines with regex."""
    rows = []
    total_paid = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "TOTAL PAID" in line.upper():
            # Try to extract the last dollar amount on the line
            amounts = re.findall(r"[\-\$\d,]+\.\d{2}", line)
            if amounts:
                try:
                    total_paid = _clean_amount(amounts[-1])
                except Exception:
                    pass
            continue

        m = LINE_RE.match(line)
        if m:
            date_raw, inv, desc, gross, discount, net = m.groups()
            try:
                rows.append({
                    "invoice_date": date_raw,
                    "invoice_number": inv,
                    "description": desc.strip() if desc.strip() else None,
                    "gross_amount": _clean_amount(gross),
                    "discount_amount": _clean_amount(discount),
                    "net_amount": _clean_amount(net),
                })
            except Exception:
                continue

    return rows, total_paid


def _fused_cell_recovery(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Split merged date+invoice cells using regex."""
    fused_re = re.compile(r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+([A-Z0-9].*)$")
    for row in rows:
        inv = row.get("invoice_number", "")
        date_val = row.get("invoice_date", "")
        if not date_val and inv:
            m = fused_re.match(inv)
            if m:
                row["invoice_date"] = m.group(1)
                row["invoice_number"] = m.group(2)
    return rows


def extract_line_items(file_bytes: bytes) -> Tuple[List[Dict[str, Any]], Optional[float]]:
    """Extract line items from a PDF using the strategy chain.

    Returns (rows, total_paid) where rows is a list of dicts with amounts as floats
    and dates as ISO strings after processing.
    """
    # Strategy 1: pdfplumber
    rows, total_paid = _strategy_pdfplumber(file_bytes)

    # Strategy 2: regex fallback
    if not rows:
        text = _extract_text_with_pymupdf(file_bytes)
        rows, total_paid = _strategy_regex(text)

    # Post-processing fixes
    rows = _fused_cell_recovery(rows)

    # Date format detection and normalization
    all_dates = [r["invoice_date"] for r in rows if r.get("invoice_date")]
    day_first = _detect_day_first(all_dates)

    for r in rows:
        if r.get("invoice_date"):
            r["invoice_date"] = _parse_date(r["invoice_date"], day_first=day_first)

    return rows, total_paid
