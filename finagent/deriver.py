"""Stage 6b: derive missing metrics that are arithmetic consequences of
extracted ones.

Some statements never print a line we expect (Airtel's BS has no subtotal
rows; BMW prints no total_liabilities), yet the accounting identities the
validator already trusts fix the value exactly. Derivations run AFTER
validation (no feedback into the proofs) and are reported with their own
DERIVED status — never VERIFIED, because a derived value satisfies the
deriving identity by construction.

Rules:
- inputs must be extracted with status VERIFIED or PROBABLE (a FLAGGED
  value failed a check; building on it spreads the damage)
- no chaining: derived values are never inputs (single pass)
- these are all-positive metrics; a non-positive result is discarded
- ordered formulas: the first computable one wins
"""
from .validator import MetricVerdict, Status

# target <- [(input_metric, sign), ...]
DERIVATIONS = [
    ("total_liabilities", [("total_equity_and_liabilities", 1), ("total_equity", -1)]),
    ("total_liabilities", [("total_assets", 1), ("total_equity", -1)]),
    ("total_equity", [("total_equity_and_liabilities", 1), ("total_liabilities", -1)]),
    ("total_equity", [("total_assets", 1), ("total_liabilities", -1)]),
    ("current_assets", [("total_assets", 1), ("non_current_assets", -1)]),
    ("non_current_assets", [("total_assets", 1), ("current_assets", -1)]),
    ("current_liabilities", [("total_liabilities", 1), ("non_current_liabilities", -1)]),
    ("non_current_liabilities", [("total_liabilities", 1), ("current_liabilities", -1)]),
    # the balance-sheet identity itself: both sides are the same number
    ("total_equity_and_liabilities", [("total_assets", 1)]),
    ("total_assets", [("total_equity_and_liabilities", 1)]),
    ("total_income", [("revenue", 1), ("other_income", 1)]),
    # some P&Ls print tax only as Current/Deferred sub-lines with no total
    # (Airtel). Sign risk, documented: an EU-convention file (tax printed
    # negative) with tax MISSING would derive the positive magnitude — no
    # such case in corpus, and the positive-only guard logs any oddity.
    ("tax_expense", [("profit_before_tax", 1), ("net_profit", -1)]),
]

_TRUSTED = {Status.VERIFIED, Status.PROBABLE}


def _expr(formula, inputs):
    parts = [f"{'-' if s < 0 else '+'} {m}[{i.status.value[0]}]"
             for (m, s), i in zip(formula, inputs)]
    return " ".join(parts).lstrip("+ ")


def derive(report):
    """Fill MISSING verdicts in a ValidationReport with DERIVED ones."""
    verdicts = report.verdicts
    by_target = {}
    for target, formula in DERIVATIONS:
        by_target.setdefault(target, []).append(formula)
    for target, formulas in by_target.items():
        v = verdicts.get(target)
        if v is None or v.status != Status.MISSING:
            continue
        # all computable formulas compete; the one resting on the fewest
        # unproven (non-VERIFIED) inputs wins — code order only breaks ties
        candidates = []
        for order, formula in enumerate(formulas):
            inputs = [verdicts.get(m) for m, _ in formula]
            if any(i is None or i.status not in _TRUSTED for i in inputs):
                continue
            unproven = sum(1 for i in inputs if i.status != Status.VERIFIED)
            candidates.append((unproven, order, formula, inputs))
        if not candidates:
            continue
        _, _, formula, inputs = min(candidates, key=lambda c: c[:2])
        value = sum(sign * i.value for (_, sign), i in zip(formula, inputs))
        if value <= 0:
            # a non-positive result means an upstream extraction is corrupt —
            # keep MISSING but leave the diagnostic, don't discard silently
            v.checks_failed.append(
                f"derivation discarded (non-positive): {_expr(formula, inputs)}")
            continue
        verdicts[target] = MetricVerdict(
            metric=target, status=Status.DERIVED, value=value,
            sources=["derived"],
            page=inputs[0].page,
            checks_passed=[f"derived: {_expr(formula, inputs)}"])
    return report
