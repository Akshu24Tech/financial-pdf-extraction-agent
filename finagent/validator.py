"""Stage 6: prove which extracted values are correct.

Financial statements are self-verifying: accounting identities and
cross-statement ties let us confirm a value without any ground truth.
Verdict per metric:

    VERIFIED  - passed at least one independent mathematical check
    PROBABLE  - extracted, nothing contradicts it, nothing confirms it
    FLAGGED   - failed a check -> human review
    MISSING   - expected but not extracted
"""
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from statistics import median


class Status(str, Enum):
    VERIFIED = "VERIFIED"
    PROBABLE = "PROBABLE"
    FLAGGED = "FLAGGED"
    MISSING = "MISSING"
    DERIVED = "DERIVED"   # filled in by the deriver stage, never by extraction


# (name, lhs metrics, rhs metrics, optional rhs metrics)
# meaning sum(lhs) == sum(rhs); optional members join only when extracted
IDENTITY_CHECKS = [
    ("balance_sheet_identity",
     ["total_assets"], ["total_liabilities", "total_equity"], []),
    ("equity_liabilities_total",
     ["total_assets"], ["total_equity_and_liabilities"], []),
    ("assets_composition",
     ["total_assets"], ["current_assets", "non_current_assets"], []),
    ("liabilities_composition",
     ["total_liabilities"], ["current_liabilities", "non_current_liabilities"], []),
    ("total_income_buildup",
     ["total_income"], ["revenue", "other_income"], []),
    ("net_profit_buildup",
     ["profit_before_tax"], ["net_profit", "tax_expense"], []),
    ("cash_flow_total",
     ["net_change_in_cash"],
     ["cash_from_operations", "cash_from_investing", "cash_from_financing"],
     ["fx_effect_on_cash"]),
]

# charges presented as a positive figure in Indian reports but as a negative
# line in EU/IFRS layouts ("Income taxes  − 2,785"); identities must hold
# under either convention
SIGN_AMBIGUOUS = {"tax_expense"}

# the same number must appear in two statements: (name, metric_a, metric_b)
CROSS_STATEMENT_CHECKS = [
    ("closing_cash_ties_to_balance_sheet", "cash_and_equivalents", "closing_cash"),
]


def within_tolerance(a, b, rel=0.005, abs_floor=2.0):
    """Rounding-aware equality: reports round to the printed unit, so a sum
    of rounded line items can legitimately differ by a few units."""
    return abs(a - b) <= max(abs_floor, rel * max(abs(a), abs(b)))


@dataclass
class MetricVerdict:
    metric: str
    status: Status
    value: float = None
    sources: list = field(default_factory=list)
    page: int = None
    checks_passed: list = field(default_factory=list)
    checks_failed: list = field(default_factory=list)


class Validator:
    def __init__(self, expected_metrics=None):
        # metric -> list of (value, source, page, label_text)
        self.values = defaultdict(list)
        self.expected = expected_metrics or []

    def add(self, metric, value, source, page=None, label_text=None):
        self.values[metric].append((float(value), source, page, label_text))

    def _consensus(self, metric):
        """Median of proposals — one wild value can't drag it."""
        vals = self.values.get(metric)
        return median(v for v, *_ in vals) if vals else None

    def validate(self):
        consensus = {m: self._consensus(m) for m in self.values}
        passed, failed = defaultdict(list), defaultdict(list)

        def totals(metrics):
            """All defensible sums: a negative sign-ambiguous charge also
            contributes its flipped value as an alternative."""
            if any(consensus.get(m) is None for m in metrics):
                return None
            sums = [0.0]
            for m in metrics:
                v = consensus[m]
                if m in SIGN_AMBIGUOUS and v < 0:
                    sums = [s + v for s in sums] + [s - v for s in sums]
                else:
                    sums = [s + v for s in sums]
            return sums

        # extractors that disagree flag their metric
        for m, obs in self.values.items():
            if len(obs) > 1:
                agree = all(within_tolerance(v, consensus[m]) for v, *_ in obs)
                (passed if agree else failed)[m].append("cross_extractor_voting")

        # accounting identities. Optional members (fx effect) sit INSIDE the
        # sum in some layouts (BMW) but OUTSIDE it, in the opening->closing
        # reconciliation, in others (Airtel "(a+b+c)") — the identity passes
        # if either reading ties. The with-fx reading is tried first so fx
        # keeps its VERIFIED credit where it genuinely belongs to the sum.
        for name, lhs, rhs, opt in IDENTITY_CHECKS:
            present = [m for m in opt if consensus.get(m) is not None]
            ls = totals(lhs)
            if ls is None or totals(rhs) is None:
                continue
            variants = ([rhs + present] if present else []) + [rhs]
            ok_members = next(
                (members for members in variants
                 if any(within_tolerance(l, r)
                        for l in ls for r in totals(members))),
                None)
            detail = f"{name} ({ls[0]:,.1f} vs {totals(rhs)[0]:,.1f})"
            if ok_members is not None:
                for m in lhs + ok_members:
                    passed[m].append(detail)
            else:
                for m in lhs + rhs + present:
                    failed[m].append(detail)

        # cross-statement ties
        for name, a, b in CROSS_STATEMENT_CHECKS:
            va, vb = consensus.get(a), consensus.get(b)
            if va is None or vb is None:
                continue
            detail = f"{name} ({va:,.1f} vs {vb:,.1f})"
            for m in (a, b):
                (passed if within_tolerance(va, vb) else failed)[m].append(detail)

        verdicts = {}
        for m, obs in self.values.items():
            value = consensus[m]
            best = min(obs, key=lambda o: abs(o[0] - value))
            status = (Status.FLAGGED if failed[m]
                      else Status.VERIFIED if passed[m]
                      else Status.PROBABLE)
            verdicts[m] = MetricVerdict(
                metric=m, status=status, value=value,
                sources=sorted({s for _, s, _, _ in obs}),
                page=best[2], checks_passed=passed[m], checks_failed=failed[m])
        for m in self.expected:
            if m not in verdicts:
                verdicts[m] = MetricVerdict(metric=m, status=Status.MISSING)
        return ValidationReport(verdicts)


class ValidationReport:
    def __init__(self, verdicts):
        self.verdicts = verdicts

    def by_status(self, status):
        return [v for v in self.verdicts.values() if v.status == status]

    def print_summary(self):
        icon = {Status.VERIFIED: "[OK]", Status.PROBABLE: "[?] ",
                Status.FLAGGED: "[!!]", Status.MISSING: "[--]",
                Status.DERIVED: "[=>]"}
        print("=" * 72)
        for status in (Status.FLAGGED, Status.MISSING, Status.DERIVED,
                       Status.VERIFIED, Status.PROBABLE):
            for v in sorted(self.by_status(status), key=lambda x: x.metric):
                val = f"{v.value:,.1f}" if v.value is not None else "-"
                src = ",".join(v.sources) if v.sources else "-"
                print(f"{icon[v.status]} {v.metric:<32} {val:>15}  [{src}]")
                for c in v.checks_failed:
                    print(f"      failed: {c}")
        print("-" * 72)
        c = {s: len(self.by_status(s)) for s in Status}
        print(f"VERIFIED: {c[Status.VERIFIED]}   PROBABLE: {c[Status.PROBABLE]}   "
              f"FLAGGED: {c[Status.FLAGGED]}   DERIVED: {c[Status.DERIVED]}   "
              f"MISSING: {c[Status.MISSING]}")
        print("=" * 72)

    def to_dict(self):
        return {m: {"status": v.status.value, "value": v.value,
                    "sources": v.sources, "page": v.page,
                    "checks_passed": v.checks_passed,
                    "checks_failed": v.checks_failed}
                for m, v in self.verdicts.items()}
