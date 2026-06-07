"""7-family rule-based classification engine.

All rules were extracted from the UNFI deduction pattern reference CSV during
design time.  The production system does NOT read the CSV at runtime.
"""

from .models import ClassificationResult


# === FAMILY 1: FSR* -> Fairshare ===========================================
#
# SOURCE: UNFI deduction pattern reference.csv (468 rows)
#
# Documented Fairshare customer codes extracted from the reference CSV:
#   FGE     -> Giant Eagle        (FSRFGE...)
#   AHOLD   -> Stop & Shop        (FSRAHOLD...)
#   DLHZE   -> Delhaize           (FSRDLHZE...)
#   FLN     -> Food Lion          (FSRFLN...)
#   HAN     -> Hannaford          (FSRHAN...)
#   HRT     -> Harris Teeter      (FSRHRT...)
#   KG      -> Kroger             (FSRKG..., KGFSR...)
#   PBG     -> Publix             (FSRPBG...)
#   SCHNK   -> Schnuck's          (FSRSCHNK...)
#   SPR     -> Sprouts            (FSRSPR...)
#   TFM     -> Fresh Market       (FSRTFM..., FSRTFMGROC..., FSRTFMVMS...)
#   WEIS    -> Weis               (FSRWEIS...)
#   WGM     -> Wegman's           (FSRWGM...)
#
# CODES FROM ACTUAL RA DATA THAT ARE NOT IN THE REFERENCE CSV:
#   HAR  -- substring search of all 468 rows: 0 exact cell matches.
#           Two plausible interpretations from the reference:
#           (a) HAR might be an abbreviation of HARVES (Row 35, 3rd Party
#               Billing, customer="Harvest Health Foods") -- HAR = first 3
#               letters of HARVES.
#           (b) HAR might be a variant of HRT (Row 185, Fairshare,
#               customer="Harris Teeter") -- 2/3 characters match.
#           No FSRHAR pattern exists in the reference.
#   HAG  -- substring search of all 468 rows: 0 exact cell matches.
#           Plausible interpretation: HAG might be an abbreviation of
#           HAGGEN (Row 33, 3rd Party Billing, customer="Haggen") --
#           HAG = first 3 letters of HAGGEN.
#           No FSRHAG pattern exists in the reference.
#   NSG  -- substring search of all 468 rows: 0 matches of any kind.
#           Does not appear anywhere in the reference CSV.
#           (Note: NCG appears in Row 234 as 3rd Party Billing with
#           customer="NCG", but NSG is completely absent.)
#
# Because these are plausible hypotheses without direct evidence in the
# Fairshare section of the reference, the classifier returns the correct
# category (Fairshare) with customer=None rather than guessing.
# ===========================================================================
FSR_CUSTOMERS = {
    "SPR": "Sprouts",
    "KG": "Kroger",
    "HRT": "Harris Teeter",
    "HAN": "Hannaford",
    "FGE": "Giant Eagle",
    "AHOLD": "Stop & Shop",
    "DLHZE": "Delhaize",
    "FLN": "Food Lion",
    "PBG": "Publix",
    "SCHNK": "Schnuck's",
    "TFM": "Fresh Market",
    "WEIS": "Weis",
    "WGM": "Wegman's",
}

# === FAMILY 2: WFM* -> Fairshare ===========================================
WFM_PROGRAMS = {
    "ISEWB": "Whole Foods In-Store Execution Whole Body",
    "ISEGR": "Whole Foods In-Store Execution Grocery",
    "ISE": "Whole Foods In-Store Execution",
    "EDPWB": "Whole Foods Education Platform Whole Body",
    "EDPGR": "Whole Foods Education Platform Grocery",
    "EDP": "Whole Foods Education Platform",
    "DCMSWB": "Whole Foods DCMS Whole Body",
    "DCMSGR": "Whole Foods DCMS Grocery",
    "DCMS": "Whole Foods DCMS",
    "PLANWB": "Whole Foods Audit Whole Body",
    "PLANGR": "Whole Foods Audit Grocery",
    "PLAN": "Whole Foods Audit",
}

# Month codes that appear in WFM invoice numbers
_MONTH_CODES = ("SEP", "OCT", "NOV", "DEC", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG")
_MONTH_SET = set(_MONTH_CODES)
# Precompute digit-removal translation table for speed.
_REMOVE_DIGITS = str.maketrans("", "", "0123456789")
# Precompute sorted mappings (longest match first) so we don't sort on every call.
_FSR_CUSTOMERS_SORTED = sorted(FSR_CUSTOMERS.items(), key=lambda x: -len(x[0]))
_WFM_PROGRAMS_SORTED = sorted(WFM_PROGRAMS.items(), key=lambda x: -len(x[0]))


def _extract_wfm_suffix(inv: str) -> str:
    """Strip WFM prefix, month code, and all digits from a WFM invoice.

    Example: WFMAUG2558031ISEWBB -> ISEWBB
    """
    body = inv[3:]  # Remove WFM prefix
    if body[:3] in _MONTH_SET:
        body = body[3:]
    return body.translate(_REMOVE_DIGITS)


def classify(invoice_number: str) -> ClassificationResult:
    """Classify an invoice number into one of the 7 families.

    Returns ClassificationResult with category, optional subcategory/region/customer.
    """
    if not invoice_number:
        return ClassificationResult(category="UNCLASSIFIED")

    inv = invoice_number.upper().strip()

    # === FAMILY 1: FSR* / KGFSR* -> Fairshare ===
    if inv.startswith("FSR") or inv.startswith("KGFSR"):
        # Normalize: KGFSR -> FSRKG for lookup
        if inv.startswith("KGFSR"):
            base = inv[5:]  # Remove KGFSR
            prefix = "KG"
        else:
            base = inv[3:]  # Remove FSR
            prefix = None

        # Strip FY suffix if present
        base = base.split("FY")[0]

        if prefix:
            # We already know the prefix from KGFSR
            customer = FSR_CUSTOMERS.get(prefix)
            return ClassificationResult(
                category="Fairshare",
                subcategory=customer,
                customer=customer,
            )

        # Find longest matching customer code
        for code, customer in _FSR_CUSTOMERS_SORTED:
            if base.startswith(code):
                return ClassificationResult(
                    category="Fairshare",
                    subcategory=customer,
                    customer=customer,
                )
        return ClassificationResult(category="Fairshare")

    # === FAMILY 2: WFM* -> Fairshare ===
    if inv.startswith("WFM"):
        suffix = _extract_wfm_suffix(inv)
        for prog_suffix, program in _WFM_PROGRAMS_SORTED:
            if suffix.startswith(prog_suffix):
                return ClassificationResult(
                    category="Fairshare",
                    subcategory=program,
                    customer="Whole Foods",
                )
        return ClassificationResult(
            category="Fairshare",
            customer="Whole Foods",
        )

    # === FAMILY 3: ERTT* / WRTT* -> Food Show ===
    if inv.startswith("ERTT"):
        return ClassificationResult(
            category="Food Show", region="East"
        )
    if inv.startswith("WRTT"):
        return ClassificationResult(
            category="Food Show", region="West"
        )

    # === FAMILY 4: ERDC / WRDC -> Advertising Quarterly ===
    # Exception per reference analysis: WRDCE (with trailing E) is Monthly, not Quarterly.
    if inv.startswith("WRDCE"):
        return ClassificationResult(
            category="Advertising - Monthly", region="West"
        )
    if inv.startswith("ERDC"):
        return ClassificationResult(
            category="Advertising - Quarterly", region="East"
        )
    if inv.startswith("WRDC"):
        return ClassificationResult(
            category="Advertising - Quarterly", region="West"
        )

    # === FAMILY 5: ERNC / WRNC -> Advertising Monthly ===
    if inv.startswith("ERNC"):
        return ClassificationResult(
            category="Advertising - Monthly",
            region="East",
            customer="Natural Connection",
        )
    if inv.startswith("WRNC"):
        return ClassificationResult(
            category="Advertising - Monthly",
            region="West",
            customer="Natural Connection",
        )

    # === FAMILY 6: MCB -> Manufacturer Charge Back ===
    if inv.startswith("MCB"):
        return ClassificationResult(
            category="MCB (Customer Specific)"
        )

    # === FAMILY 7: YKS -> 3rd Party Billing ===
    if inv.startswith("YKS"):
        return ClassificationResult(
            category="3rd Party Billing",
            customer="Yokes Specialty",
        )

    # === UNCLASSIFIED ===
    return ClassificationResult(category="UNCLASSIFIED")
