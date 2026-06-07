"""Stage 1: Document Identification — Hard Filters.

Binary pass/fail.  No scoring.
"""

import re
from typing import List, BinaryIO
import fitz  # pymupdf
from .models import DocumentCheckResult

# Known UNFI invoice prefixes extracted from reference CSV analysis.
KNOWN_PREFIXES = {
    "WFM", "FSR", "KGFSR", "ERTT", "WRTT",
    "ERDC", "WRDC", "ERNC", "WRNC", "MCB", "YKS",
}


def _has_unfi_company_name(text: str) -> bool:
    return "United Natural Foods" in text


# Pre-compile a single regex for all known prefixes (longest first to avoid partial matches).
_PREFIX_PATTERN = re.compile(
    "|".join(re.escape(p) for p in sorted(KNOWN_PREFIXES, key=len, reverse=True))
)


def _has_known_invoice_prefix(text: str) -> bool:
    """Check if text contains at least one known UNFI invoice prefix."""
    return _PREFIX_PATTERN.search(text) is not None


def _has_tabular_data(text: str) -> bool:
    """Look for table header row typical of RA documents."""
    return "INVOICE DATE" in text and "INVOICE NUMBER" in text and "NET AMOUNT" in text


def _has_total_paid(text: str) -> bool:
    return "TOTAL PAID" in text


def check_document(file_obj: BinaryIO, filename: str) -> DocumentCheckResult:
    """Check if a single PDF is a valid RA document.

    Returns DocumentCheckResult with status:
      - VALID_RA     : passes all conditions
      - CORRUPTED_RA : has company name + prefixes but missing structure
      - NOISE        : fails minimum qualifying conditions
    """
    try:
        doc = fitz.open(stream=file_obj.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
    except Exception:
        # Any exception means "not a valid PDF — treat as NOISE"
        return DocumentCheckResult(
            filename=filename, status="NOISE"
        )

    result = DocumentCheckResult(
        filename=filename,
    )

    # === Minimum Qualifying Conditions ===
    has_company = _has_unfi_company_name(text)
    has_prefixes = _has_known_invoice_prefix(text)

    if not (has_company and has_prefixes):
        result.status = "NOISE"
        return result

    # === Structural Integrity Check ===
    result.has_advice_date_header = "ADVICE DATE" in text
    result.has_advice_number_header = "ADVICE NUMBER" in text
    result.has_tabular_data = _has_tabular_data(text)
    result.has_total_paid = _has_total_paid(text)

    # Require the three core structural elements.
    # TOTAL PAID is a soft check: if missing we still accept the RA
    # as long as we can extract line items (validated downstream).
    all_structural = (
        result.has_advice_date_header
        and result.has_advice_number_header
        and result.has_tabular_data
    )

    # Try to extract advice date/number for response enrichment
    if result.has_advice_date_header and result.has_advice_number_header:
        # Look for advice number after the header line
        # The header block is:
        #   ADVICE DATE
        #   ADVICE NUMBER
        #   <date>
        #   <number>
        m = re.search(
            r"ADVICE\s+DATE.*?ADVICE\s+NUMBER\s*\n\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s*\n\s*(\d{5,})",
            text,
            re.DOTALL,
        )
        if m:
            result.advice_date = m.group(1)
            result.advice_number = m.group(2)

    if all_structural:
        result.status = "VALID_RA"
    else:
        result.is_corrupted = True
        result.status = "CORRUPTED_RA"

    return result


def identify_single_ra(documents: List[DocumentCheckResult]) -> DocumentCheckResult:
    """From a list of checked documents, return exactly one valid RA.

    Raises ValueError if 0 or >1 valid RAs are found.
    """
    valid_ras = [d for d in documents if d.status == "VALID_RA"]

    if len(valid_ras) == 0:
        corrupted = [d for d in documents if d.status == "CORRUPTED_RA"]
        if corrupted:
            raise ValueError(
                "CORRUPTED_RA — missing required headers (ADVICE_DATE, ADVICE_NUMBER). "
                "Human review required."
            )
        raise ValueError("No valid RA document found in batch.")

    if len(valid_ras) > 1:
        raise ValueError(
            f"Multiple valid RA documents found ({len(valid_ras)}). "
            f"Expected exactly 1 per email batch. "
            f"Files: {[d.filename for d in valid_ras]}"
        )

    return valid_ras[0]
