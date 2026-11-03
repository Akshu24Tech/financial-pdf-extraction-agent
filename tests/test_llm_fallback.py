"""LLM fallback: the LLM proposes, the validator decides.

No real model is called. A FakeChooser answers like a model would, so these
tests check OUR logic: what gets accepted, what gets rejected, and that no
answer can push a wrong number past the accounting identities. CI stays
deterministic, free and fast. The real model is evaluated separately
(experiments/llm_fallback_eval.py).
"""

import pytest

from finagent.llm_fallback import GeminiChooser, GroqChooser, chooser_from_env, parse_line_id
from finagent.pipeline import run
from tests.test_e2e import make_report


class FakeChooser:
    """Picks the line whose label equals answers[metric]; records every call."""

    def __init__(self, answers=None, error=None):
        self.answers, self.error, self.calls = answers or {}, error, []

    def choose(self, metric, statement, lines):
        self.calls.append((metric, statement, [label for label, _ in lines]))
        if self.error:
            raise self.error
        wanted = self.answers.get(metric)
        labels = [label for label, _ in lines]
        return labels.index(wanted) if wanted in labels else None


def _run(tmp_path, chooser, **report_kwargs):
    pdf = tmp_path / "r.pdf"
    make_report(pdf, **report_kwargs)
    return run(pdf, out_path=tmp_path / "r.xlsx", verbose=False, chooser=chooser).to_dict()


# Decorated labels, copied from real held-out reports (Shivalik Bimetal).
DECORATED_PROFIT = {"Profit for the year": "XI Profit for the years (IX-X)"}
DECORATED_CLOSING = {
    "Cash and cash equivalents at the end of the year": "Cash and Cash equivalents at the closing of year"
}


# ---------------------------------------------------------------- accepting --
def test_rules_alone_miss_the_decorated_label(tmp_path):
    """The premise: without the LLM, this label is MISSING."""
    m = _run(tmp_path, None, relabel=DECORATED_PROFIT)
    assert m["net_profit"]["status"] == "MISSING"


def test_correct_pick_is_accepted_verified_and_tagged(tmp_path):
    fake = FakeChooser({"net_profit": "XI Profit for the years (IX-X)"})
    m = _run(tmp_path, fake, relabel=DECORATED_PROFIT)
    assert m["net_profit"]["value"] == pytest.approx(14625.00)
    assert m["net_profit"]["status"] == "VERIFIED"
    assert m["net_profit"]["sources"] == ["llm"]  # the receipt says how it was found
    assert any("net_profit_buildup" in c for c in m["net_profit"]["checks_passed"])


def test_decorated_closing_cash_is_accepted_via_cross_statement_tie(tmp_path):
    fake = FakeChooser({"closing_cash": "Cash and Cash equivalents at the closing of year"})
    m = _run(tmp_path, fake, relabel=DECORATED_CLOSING)
    assert m["closing_cash"]["status"] == "VERIFIED"
    assert m["closing_cash"]["value"] == pytest.approx(9875.35)


def test_only_missing_metrics_are_asked_about(tmp_path):
    fake = FakeChooser({"net_profit": "XI Profit for the years (IX-X)"})
    _run(tmp_path, fake, relabel=DECORATED_PROFIT)
    asked = {metric for metric, _, _ in fake.calls}
    assert "net_profit" in asked
    assert not asked & {"revenue", "total_assets", "profit_before_tax"}  # rules found these


def test_lines_already_used_by_rules_are_not_offered(tmp_path):
    fake = FakeChooser()
    _run(tmp_path, fake, relabel=DECORATED_PROFIT)
    offered = {
        label for _, statement, labels in fake.calls if statement == "PL" for label in labels
    }
    assert "Profit before tax" not in offered
    assert "XI Profit for the years (IX-X)" in offered


# ---------------------------------------------------------------- rejecting --
def test_wrong_line_is_rejected_by_the_identity(tmp_path):
    """The model picks a real line from the page, just the wrong one."""
    report = {"relabel": DECORATED_PROFIT, "extra_pl_rows": [("Exceptional items", 1250.00, 0.00)]}
    m = _run(tmp_path, FakeChooser({"net_profit": "Exceptional items"}), **report)
    assert m["net_profit"]["status"] == "MISSING"
    # and the rejected guess left no trace: the result is exactly what the
    # rules alone produce
    assert m == _run(tmp_path, None, **report)


def test_llm_picks_that_only_agree_with_each_other_are_rejected(tmp_path):
    """PBT, tax and net profit all unrecognisable to the rules. Even if the LLM
    picks all three correctly, the identity then only checks LLM against LLM,
    which proves nothing. All three must stay MISSING."""
    relabel = {
        "Profit before tax": "Earnings pre levy",
        "Total tax expense": "Levy charge",
        "Profit for the year": "Residual earnings",
    }
    baseline = _run(tmp_path, None, relabel=relabel)
    assert {baseline[m]["status"] for m in ("profit_before_tax", "tax_expense", "net_profit")} == {
        "MISSING"
    }

    fake = FakeChooser(
        {
            "profit_before_tax": "Earnings pre levy",
            "tax_expense": "Levy charge",
            "net_profit": "Residual earnings",
        }
    )
    m = _run(tmp_path, fake, relabel=relabel)
    for metric in ("profit_before_tax", "tax_expense", "net_profit"):
        assert m[metric]["status"] == "MISSING", metric


def test_null_answer_stays_missing(tmp_path):
    m = _run(tmp_path, FakeChooser({}), relabel=DECORATED_PROFIT)
    assert m["net_profit"]["status"] == "MISSING"


def test_provider_error_never_fails_the_run(tmp_path):
    m = _run(tmp_path, FakeChooser(error=TimeoutError("model down")), relabel=DECORATED_PROFIT)
    assert m["net_profit"]["status"] == "MISSING"
    assert m["revenue"]["status"] == "VERIFIED"  # everything else unaffected


def test_fallback_off_changes_nothing_on_a_clean_report(tmp_path):
    with_fake = _run(tmp_path, FakeChooser())
    without = _run(tmp_path, None)
    assert with_fake == without


# ---------------------------------------------------------- output parsing --
@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"line_id": 3}', 3),
        ('{"line_id": 0}', 0),
        ('{"line_id": null}', None),
        ('{"line_id": 99}', None),  # out of range: not a line we showed
        ('{"line_id": -1}', None),
        ('{"line_id": true}', None),  # bool is an int in Python; reject it
        ('{"line_id": "3"}', None),
        ('{"line_id": 14625.0}', None),  # a number instead of an ID
        ("line 3", None),  # not JSON
        ("[3]", None),
    ],
)
def test_parse_line_id_accepts_only_valid_ids(text, expected):
    assert parse_line_id(text, n_lines=10) == expected


def test_fallback_is_off_unless_configured(monkeypatch):
    for var in ("FINAGENT_LLM_PROVIDER", "GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert chooser_from_env() is None
    monkeypatch.setenv("FINAGENT_LLM_PROVIDER", "gemini")
    assert chooser_from_env() is None  # provider without a key = off
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert isinstance(chooser_from_env(), GeminiChooser)
    monkeypatch.setenv("FINAGENT_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    assert isinstance(chooser_from_env(), GroqChooser)
