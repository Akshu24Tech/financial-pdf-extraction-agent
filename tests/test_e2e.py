"""End-to-end test: synthetic annual report PDF -> full pipeline -> assert.

Why this exists: the real annual reports are copyrighted and gitignored, so
CI never ran the pipeline from PDF to numbers. Unit tests can stay green while
the locator, extractor or validator is broken. This test closes that gap.

Why generate the PDF in code (instead of committing one):
- we wrote every number, so the expected values are EXACT ground truth
- no copyright issue, no binary blob in git, and the report is readable here
- changing a number to create a new scenario is a one-line edit

Two scenarios, because a verifier is only proven if it can say NO:
- CLEAN report: every identity holds -> metrics must come out VERIFIED
- BROKEN report: one deliberate typo -> the validator must FLAG exactly the
  numbers involved, and nothing else (the blast radius is contained)
"""

# Deliberately NOT importorskip: if reportlab ever went missing from CI, a skip
# would turn this test silently green. A loud ImportError is the safe failure.
# Locally: pip install reportlab
import pytest
from openpyxl import load_workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from finagent.pipeline import run

# ---------------------------------------------------------------------------
# Ground truth. (label as printed, current year, prior year). Numbers are in
# INR crore with two decimals and Indian lakh grouping, like real reports.
# Every identity the validator knows holds in BOTH year columns.
# ---------------------------------------------------------------------------
BALANCE_SHEET = [
    ("ASSETS", None, None),
    ("Total non-current assets", 85420.50, 79310.20),
    ("Inventories", 12450.00, 11020.30),
    ("Trade receivables", 18760.40, 16540.10),
    ("Cash and cash equivalents", 9875.35, 6573.00),
    ("Total current assets", 64310.25, 57890.40),
    ("TOTAL ASSETS", 149730.75, 137200.60),
    ("EQUITY AND LIABILITIES", None, None),
    ("Total equity", 82115.60, 74305.25),
    ("Total non-current liabilities", 28404.15, 27110.85),
    ("Total current liabilities", 39211.00, 35784.50),
    ("Total liabilities", 67615.15, 62895.35),
    ("TOTAL EQUITY AND LIABILITIES", 149730.75, 137200.60),
]

PROFIT_AND_LOSS = [
    ("Revenue from operations", 102340.80, 94120.45),
    ("Other income", 2150.20, 1880.55),
    ("Total income", 104491.00, 96001.00),
    ("Employee benefits expense", 18230.10, 16905.40),
    ("Depreciation and amortisation expense", 6420.35, 5980.20),
    ("Finance costs", 3115.55, 2870.10),
    ("Total expenses", 84991.00, 78501.00),
    ("Profit before tax", 19500.00, 17500.00),
    ("Total tax expense", 4875.00, 4375.00),
    ("Profit for the year", 14625.00, 13125.00),
    ("Basic earnings per share", 45.62, 40.94),
]

CASH_FLOW = [
    ("Net cash generated from operating activities", 21340.75, 18230.40),
    ("Net cash used in investing activities", -9812.40, -8940.10),
    ("Net cash used in financing activities", -8226.00, -7120.30),
    ("Net increase in cash and cash equivalents", 3302.35, 2170.00),
    ("Cash and cash equivalents at the beginning of the year", 6573.00, 4403.00),
    ("Cash and cash equivalents at the end of the year", 9875.35, 6573.00),
]

# The metrics each statement's identities can prove. A value here must come out
# VERIFIED on the clean report; anything less means verification regressed.
MUST_VERIFY = {
    "total_assets": 149730.75,
    "non_current_assets": 85420.50,
    "current_assets": 64310.25,
    "total_equity": 82115.60,
    "total_liabilities": 67615.15,
    "current_liabilities": 39211.00,
    "non_current_liabilities": 28404.15,
    "total_equity_and_liabilities": 149730.75,
    "revenue": 102340.80,
    "other_income": 2150.20,
    "total_income": 104491.00,
    "profit_before_tax": 19500.00,
    "tax_expense": 4875.00,
    "net_profit": 14625.00,
    "cash_from_operations": 21340.75,
    "cash_from_investing": -9812.40,
    "cash_from_financing": -8226.00,
    "net_change_in_cash": 3302.35,
    "cash_and_equivalents": 9875.35,
    "closing_cash": 9875.35,
}

# 1-based page each statement is printed on (page 1 is a prose cover page).
EXPECTED_PAGE = {"BS": 2, "PL": 3, "CF": 4}
BS_METRICS = {
    "total_assets",
    "non_current_assets",
    "current_assets",
    "total_equity",
    "total_liabilities",
    "current_liabilities",
    "non_current_liabilities",
    "total_equity_and_liabilities",
    "cash_and_equivalents",
}
PL_METRICS = {
    "revenue",
    "other_income",
    "total_income",
    "profit_before_tax",
    "tax_expense",
    "net_profit",
}
CF_METRICS = {
    "cash_from_operations",
    "cash_from_investing",
    "cash_from_financing",
    "net_change_in_cash",
    "closing_cash",
}
PAGE_OF_METRIC = {
    **dict.fromkeys(BS_METRICS, EXPECTED_PAGE["BS"]),
    **dict.fromkeys(PL_METRICS, EXPECTED_PAGE["PL"]),
    **dict.fromkeys(CF_METRICS, EXPECTED_PAGE["CF"]),
}


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------
def _indian(x):
    """Format like an Indian annual report: lakh grouping, 2 decimals,
    negatives in accounting parentheses. 102340.8 -> '1,02,340.80'."""
    neg = x < 0
    whole, frac = f"{abs(x):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    s = f"{whole}.{frac}"
    return f"({s})" if neg else s


def _statement_page(c, title, rows):
    y = 800
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Synthetic Industries Limited")
    y -= 18
    c.drawString(50, y, title)
    y -= 14
    c.setFont("Helvetica", 9)
    c.drawString(50, y, "(All amounts in INR crore, unless otherwise stated)")
    y -= 22
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(440, y, "Year ended")
    c.drawRightString(540, y, "Year ended")
    y -= 11
    c.drawRightString(440, y, "31 March 2025")
    c.drawRightString(540, y, "31 March 2024")
    y -= 18
    for label, cur, prior in rows:
        c.setFont("Helvetica-Bold" if cur is None or label.isupper() else "Helvetica", 9)
        c.drawString(50, y, label)
        if cur is not None:
            c.drawRightString(440, y, _indian(cur))
            c.drawRightString(540, y, _indian(prior))
        y -= 15
    c.showPage()


def make_report(path, overrides=None):
    """Write the 4-page synthetic report. `overrides` maps a printed label to a
    replacement current-year value, used to plant a deliberate error."""
    overrides = overrides or {}

    def apply(rows):
        return [(lbl, overrides.get(lbl, cur), prior) for lbl, cur, prior in rows]

    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 11)
    c.drawString(50, 780, "Synthetic Industries Limited - Annual Report 2024-25")
    c.drawString(50, 760, "This cover page is prose only. It mentions the balance sheet and")
    c.drawString(50, 745, "the cash flow statement but carries no figures, so the locator")
    c.drawString(50, 730, "must not pick it.")
    c.showPage()
    _statement_page(c, "Consolidated Balance Sheet as at 31 March 2025", apply(BALANCE_SHEET))
    _statement_page(
        c,
        "Consolidated Statement of Profit and Loss for the year ended 31 March 2025",
        apply(PROFIT_AND_LOSS),
    )
    _statement_page(
        c,
        "Consolidated Statement of Cash Flows for the year ended 31 March 2025",
        apply(CASH_FLOW),
    )
    c.save()


# ---------------------------------------------------------------------------
# Fixtures: run the pipeline once per scenario (it's the slow part)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def clean(tmp_path_factory):
    d = tmp_path_factory.mktemp("clean")
    make_report(d / "clean.pdf")
    report = run(d / "clean.pdf", out_path=d / "clean.xlsx", verbose=False)
    return report.to_dict(), d / "clean.xlsx"


@pytest.fixture(scope="module")
def broken(tmp_path_factory):
    # One planted typo: cash-flow closing cash (9,975.35) no longer matches
    # balance-sheet cash (9,875.35). A ~1% error, the kind a human misses.
    d = tmp_path_factory.mktemp("broken")
    make_report(
        d / "broken.pdf",
        overrides={
            "Cash and cash equivalents at the end of the year": 9975.35,
        },
    )
    report = run(d / "broken.pdf", out_path=d / "broken.xlsx", verbose=False)
    return report.to_dict()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_formatter_matches_indian_reports():
    assert _indian(102340.80) == "1,02,340.80"
    assert _indian(-9812.40) == "(9,812.40)"
    assert _indian(45.62) == "45.62"


@pytest.mark.parametrize("metric", sorted(MUST_VERIFY))
def test_clean_report_value_is_exact_and_verified(clean, metric):
    metrics, _ = clean
    m = metrics[metric]
    assert m["value"] == pytest.approx(MUST_VERIFY[metric]), f"{metric} value"
    assert m["status"] == "VERIFIED", f"{metric}: {m['status']} {m['checks_failed']}"


@pytest.mark.parametrize("metric", sorted(PAGE_OF_METRIC))
def test_clean_report_receipt_points_at_the_right_page(clean, metric):
    metrics, _ = clean
    page_index = metrics[metric]["page"]  # pipeline stores 0-based
    assert page_index is not None and page_index + 1 == PAGE_OF_METRIC[metric]


def test_clean_report_has_no_flags(clean):
    metrics, _ = clean
    flagged = {k: v["checks_failed"] for k, v in metrics.items() if v["status"] == "FLAGGED"}
    assert flagged == {}


def test_clean_report_writes_excel(clean):
    _, xlsx = clean
    wb = load_workbook(xlsx)
    assert wb.sheetnames, "workbook has no sheets"
    cells = {str(c.value).lower() for ws in wb for row in ws.iter_rows() for c in row if c.value}
    assert any("verified" in v for v in cells), "Excel lost the status column"


def test_broken_report_flags_exactly_the_planted_error(broken):
    flagged = {k for k, v in broken.items() if v["status"] == "FLAGGED"}
    assert flagged == {"cash_and_equivalents", "closing_cash"}
    assert broken["closing_cash"]["value"] == pytest.approx(9975.35)
    assert any(
        "closing_cash_ties_to_balance_sheet" in c for c in broken["closing_cash"]["checks_failed"]
    )


def test_broken_report_error_does_not_spread(broken):
    """The typo touches one cross-check. Every other metric must still verify;
    a verifier that flags everything when one thing is wrong is useless."""
    unaffected = set(MUST_VERIFY) - {"cash_and_equivalents", "closing_cash"}
    not_verified = {m: broken[m]["status"] for m in unaffected if broken[m]["status"] != "VERIFIED"}
    assert not_verified == {}
