"""Post-processing helpers for extracted line items."""

from typing import List, Dict, Any


def filter_total_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove any row where invoice_number contains TOTAL."""
    return [r for r in rows if "TOTAL" not in r.get("invoice_number", "").upper()]
