"""Unit tests for the pure-logic core of finagent.

These deliberately need NO PDF: they test number parsing, label cleaning,
fuzzy matching, the accounting-identity proofs, and derivation. That's the
project's whole thesis (accuracy comes from verification), and it's exactly
what CI can run fast on a clean machine.

Run locally:  pytest -v
"""
from finagent.normalizer import parse_number, clean_label, match_label
from finagent.validator import Validator, Status, within_tolerance
from finagent.deriver import derive
from finagent.schema import metrics_for_statement, METRICS


# ---------------------------------------------------------------------------
# parse_number: the messy-string -> float layer
# ---------------------------------------------------------------------------
def test_parse_number_indian_grouping():
    assert parse_number("1,49,982") == 149982.0


def test_parse_number_accounting_parentheses_are_negative():
    assert parse_number("(1,234.5)") == -1234.5


def test_parse_number_unicode_minus():
    assert parse_number("−112,858") == -112858.0


def test_parse_number_decimal():
    assert parse_number("8,207.65") == 8207.65


def test_parse_number_strips_footnote_marks():
    assert parse_number("1,234*") == 1234.0


def test_parse_number_nil_dash_is_none():
    assert parse_number("-") is None


def test_parse_number_non_number_is_none():
    assert parse_number("abc") is None


# ---------------------------------------------------------------------------
# clean_label: normalise a label before matching
# ---------------------------------------------------------------------------
def test_clean_label_strips_loss_qualifier():
    assert clean_label("Net profit/(loss) for the year") == "net profit for the year"


def test_clean_label_strips_leading_numbering():
    assert clean_label("1. Revenue from operations") == "revenue from operations"


def test_clean_label_strips_roman_enumerator():
    assert clean_label("(ii) Trade Receivables") == "trade receivables"


def test_clean_label_strips_leading_basis_word():
    assert clean_label("Consolidated Net Profit") == "net profit"


# ---------------------------------------------------------------------------
# match_label: fuzzy label -> canonical metric
# ---------------------------------------------------------------------------
def test_match_label_exact_synonym():
    metric, score = match_label("Revenue from operations")
    assert metric == "revenue" and score >= 88


def test_match_label_alternate_wording():
    metric, _ = match_label("Turnover")
    assert metric == "revenue"


def test_match_label_other_residual_is_rejected():
    # "Other current liabilities" is a residual line, not the total
    metric, _ = match_label("Other current liabilities")
    assert metric is None


def test_match_label_total_assets():
    metric, _ = match_label("Total Assets")
    assert metric == "total_assets"


# ---------------------------------------------------------------------------
# within_tolerance: rounding-aware equality
# ---------------------------------------------------------------------------
def test_within_tolerance_allows_rounding():
    assert within_tolerance(100.0, 100.5) is True


def test_within_tolerance_rejects_real_gap():
    assert within_tolerance(100.0, 200.0) is False


# ---------------------------------------------------------------------------
# Validator: the accounting-identity proofs (the core thesis)
# ---------------------------------------------------------------------------
def test_balance_sheet_identity_verifies():
    v = Validator(expected_metrics=["total_assets", "total_liabilities", "total_equity"])
    v.add("total_assets", 300, source="geometric")
    v.add("total_liabilities", 200, source="geometric")
    v.add("total_equity", 100, source="geometric")
    report = v.validate()
    # 300 == 200 + 100, so every term is proven
    assert report.verdicts["total_assets"].status == Status.VERIFIED


def test_broken_identity_flags():
    v = Validator(expected_metrics=["total_assets", "total_liabilities", "total_equity"])
    v.add("total_assets", 999, source="geometric")   # wrong on purpose
    v.add("total_liabilities", 200, source="geometric")
    v.add("total_equity", 100, source="geometric")
    report = v.validate()
    # 999 != 200 + 100, so the value is flagged for a human, never trusted
    assert report.verdicts["total_assets"].status == Status.FLAGGED


def test_cross_statement_cash_tie_verifies():
    v = Validator(expected_metrics=["cash_and_equivalents", "closing_cash"])
    v.add("cash_and_equivalents", 500, source="geometric")
    v.add("closing_cash", 500, source="geometric")
    report = v.validate()
    assert report.verdicts["closing_cash"].status == Status.VERIFIED


def test_unconfirmed_value_is_probable():
    # a lone value with nothing to check it against is PROBABLE, not VERIFIED
    v = Validator(expected_metrics=["revenue"])
    v.add("revenue", 12345, source="geometric")
    report = v.validate()
    assert report.verdicts["revenue"].status == Status.PROBABLE


# ---------------------------------------------------------------------------
# derive: fill a missing number the identities pin down exactly
# ---------------------------------------------------------------------------
def test_derive_missing_liabilities():
    v = Validator(expected_metrics=["total_assets", "total_equity", "total_liabilities"])
    v.add("total_assets", 300, source="geometric")
    v.add("total_equity", 100, source="geometric")
    # total_liabilities never extracted -> starts MISSING
    report = v.validate()
    assert report.verdicts["total_liabilities"].status == Status.MISSING

    report = derive(report)
    v_liab = report.verdicts["total_liabilities"]
    assert v_liab.status == Status.DERIVED
    assert v_liab.value == 200   # 300 - 100


# ---------------------------------------------------------------------------
# schema: the shared vocabulary
# ---------------------------------------------------------------------------
def test_metrics_for_statement_filters_correctly():
    bs = metrics_for_statement("BS")
    assert "total_assets" in bs
    assert "revenue" not in bs            # revenue lives on the P&L
    assert all(METRICS[m]["statement"] == "BS" for m in bs)


# ---------------------------------------------------------------------------
# unit_detector: Unit & Period Anchor Engine
# ---------------------------------------------------------------------------
def test_unit_detector_crores():
    from finagent.unit_detector import detect_unit
    u = detect_unit("Balance Sheet as of March 31, 2025 (Rs. in Crores)")
    assert u.unit_name == "Crores"
    assert u.multiplier == 10_000_000.0


def test_unit_detector_millions():
    from finagent.unit_detector import detect_unit
    u = detect_unit("Statement of Profit and Loss (in Millions)")
    assert u.unit_name == "Millions"
    assert u.multiplier == 1_000_000.0


def test_unit_detector_periods():
    from finagent.unit_detector import detect_periods
    p = detect_periods("Financial Statements for 31 March 2025 and 31 March 2024")
    assert "31 March 2025" in p.current_period
    assert "31 March 2024" in p.prior_period

