"""Stage 4: Summary generation."""

from typing import List, Dict
from .models import LineItem, ClassificationSummary


def build_summary(line_items: List[LineItem]) -> ClassificationSummary:
    """Build a summary from classified line items."""
    categories: Dict[str, int] = {}
    total_deductions = 0.0

    for item in line_items:
        categories[item.category] = categories.get(item.category, 0) + 1
        total_deductions += item.net_amount or 0.0

    return ClassificationSummary(
        total_items=len(line_items),
        total_deductions=round(total_deductions, 2),
        categories=categories,
    )
