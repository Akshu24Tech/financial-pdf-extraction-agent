"""Canonical metric schema: the single vocabulary every module speaks.

Each metric has: canonical name, the statement it lives in, and label synonyms
as they appear across different companies' reports. Synonyms are matched
fuzzily, so they don't need to be exhaustive — just representative.
"""

# statement codes: PL = profit & loss, BS = balance sheet, CF = cash flow
METRICS = {
    # ---------------- Profit & Loss ----------------
    "revenue": {
        "statement": "PL",
        # "interest earned" is the bank revenue line (Schedule III P&L)
        "synonyms": ["revenue from operations", "net sales", "income from operations",
                     "total revenues", "revenue", "sales", "turnover",
                     "interest earned"],
    },
    "other_income": {
        "statement": "PL",
        "synonyms": ["other income", "other operating income"],
    },
    "total_income": {
        "statement": "PL",
        "synonyms": ["total income", "total revenue"],
    },
    "total_expenses": {
        "statement": "PL",
        "synonyms": ["total expenses", "total expenditure", "total costs and expenses"],
    },
    "employee_costs": {
        "statement": "PL",
        "synonyms": ["employee benefit expenses", "employee benefits expense",
                     "staff costs", "personnel expenses"],
    },
    "depreciation": {
        "statement": "PL",
        "synonyms": ["depreciation and amortisation expense", "depreciation and amortization",
                     "depreciation, amortisation and impairment",
                     "depreciation amortisation and depletion expense"],
    },
    "finance_costs": {
        "statement": "PL",
        "synonyms": ["finance costs", "finance cost", "interest expense", "borrowing costs"],
    },
    "profit_before_tax": {
        "statement": "PL",
        "synonyms": ["profit before tax", "profit before income tax", "income before income taxes",
                     "profit/(loss) before tax", "earnings before tax"],
    },
    "tax_expense": {
        "statement": "PL",
        "synonyms": ["total tax expense", "tax expense", "income tax expense",
                     "provision for taxation", "income taxes"],
    },
    "net_profit": {
        "statement": "PL",
        # bank P&L wording: the before-minority-interest line is the total
        # profit (incl. NCI), matching the "profit for the year" convention
        "synonyms": ["profit for the year", "net profit", "profit after tax", "net income",
                     "profit/(loss) for the year", "profit for the period",
                     "net profit/loss",
                     "net profit for the year before minority interest",
                     "profit after tax for the year"],
    },
    "total_comprehensive_income": {
        "statement": "PL",
        "synonyms": ["total comprehensive income for the year", "total comprehensive income"],
    },
    "eps_basic": {
        "statement": "PL",
        "synonyms": ["basic earnings per share", "basic eps", "earnings per share basic",
                     "basic (in rupees)", "basic (rs.)",
                     "earnings per equity share basic",
                     # combined line when basic == diluted (TCS); EU wording (BMW)
                     "earnings per equity share basic and diluted",
                     "basic earnings per ordinary share in eur",
                     # power-sector wording (rate-regulated entities), as
                     # truncated by the line wrap; the "before net movement"
                     # twin is vetoed by the before/after directional guard
                     "basic / diluted earnings per equity share after net movement"],
    },

    # ---------------- Balance Sheet ----------------
    "total_assets": {
        "statement": "BS",
        "synonyms": ["total assets"],
    },
    "non_current_assets": {
        "statement": "BS",
        "synonyms": ["total non-current assets", "total non current assets",
                     "non-current assets"],
    },
    "current_assets": {
        "statement": "BS",
        "synonyms": ["total current assets", "current assets"],
    },
    # side: these labels recur verbatim under BOTH BS sections; the metric
    # means the CURRENT-side row (extractor stamps rows with their section)
    "inventories": {
        "statement": "BS",
        "side": "current",
        "synonyms": ["inventories", "inventory"],
    },
    "trade_receivables": {
        "statement": "BS",
        "side": "current",
        "synonyms": ["trade receivables", "accounts receivable", "sundry debtors"],
    },
    "cash_and_equivalents": {
        "statement": "BS",
        "side": "current",
        "synonyms": ["cash and cash equivalents", "cash and bank balances"],
    },
    "total_equity": {
        "statement": "BS",
        "synonyms": ["total equity", "total shareholders' equity", "shareholders' funds",
                     "equity attributable to owners", "equity"],
    },
    "non_current_liabilities": {
        "statement": "BS",
        "synonyms": ["total non-current liabilities", "total non current liabilities",
                     "non-current provisions and liabilities"],
    },
    "current_liabilities": {
        "statement": "BS",
        "synonyms": ["total current liabilities",
                     "current provisions and liabilities"],
    },
    "total_liabilities": {
        "statement": "BS",
        "synonyms": ["total liabilities"],
    },
    "total_equity_and_liabilities": {
        "statement": "BS",
        # "capital and liabilities" is the bank BS section (Schedule III)
        "synonyms": ["total equity and liabilities", "total liabilities and equity",
                     "total liabilities and shareholders' equity",
                     "total capital and liabilities"],
    },

    # ---------------- Cash Flow ----------------
    "cash_from_operations": {
        "statement": "CF",
        # NOTE: "cash generated from operations" is deliberately absent —
        # it's the PRE-TAX subtotal (golden check caught it on Reliance,
        # Adani and Newgen); only "net …" totals belong here
        "synonyms": ["net cash generated from operating activities",
                     "net cash from operating activities",
                     "net cash flow from operating activities",
                     "cash inflow/outflow from operating activities"],
    },
    "cash_from_investing": {
        "statement": "CF",
        "synonyms": ["net cash used in investing activities",
                     "net cash from investing activities",
                     "net cash flow from investing activities",
                     "cash inflow/outflow from investing activities",
                     "net cash flows generated from investing activities",
                     "net cash generated from investing activities"],
    },
    "cash_from_financing": {
        "statement": "CF",
        "synonyms": ["net cash used in financing activities",
                     "net cash from financing activities",
                     "net cash flow from financing activities",
                     "cash inflow/outflow from financing activities",
                     "net cash flows generated from financing activities",
                     "net cash generated from financing activities"],
    },
    "net_change_in_cash": {
        "statement": "CF",
        "synonyms": ["net increase/(decrease) in cash and cash equivalents",
                     "net increase in cash and cash equivalents",
                     "net change in cash and cash equivalents",
                     "net decrease in cash and cash equivalents",
                     "net increase in cash and cash equivalents during the year"],
    },
    "fx_effect_on_cash": {
        "statement": "CF",
        "optional": True,   # only multinationals report it; feeds the
                            # cash-flow identity, never counted as MISSING
        "synonyms": ["effect of exchange rate on cash and cash equivalents",
                     "effect of exchange rate changes on cash and cash equivalents",
                     "effects of exchange rate changes on cash and cash equivalents",
                     "exchange differences on cash and cash equivalents",
                     "effect of exchange differences on cash and cash equivalents",
                     "effect of fluctuation in foreign currency translation reserve",
                     "exchange difference on translation of foreign currency cash and cash equivalents"],
    },
    "closing_cash": {
        "statement": "CF",
        "synonyms": ["cash and cash equivalents at the end of the year",
                     "cash and cash equivalents at end of the period",
                     "closing cash and cash equivalents",
                     "cash and cash equivalents as at the end of the year",
                     "cash and cash equivalents as at december",
                     "closing balance of cash and cash equivalents"],
    },
}

ALL_METRICS = list(METRICS)
EXPECTED_METRICS = [m for m, d in METRICS.items() if not d.get("optional")]

def metrics_for_statement(code):
    return [m for m, d in METRICS.items() if d["statement"] == code]
