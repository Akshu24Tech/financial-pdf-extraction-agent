"""Stage 6a: LLM fallback for MISSING metrics. The LLM proposes, the validator decides.

Rules match clean labels. Real reports decorate them ("IX Profit before tax
(VII-VIII)", "Cash ... at the closing of year"), and no synonym list keeps up.
For metrics still MISSING after the rules, an LLM gets the numbered lines of the
already-located statement page and answers ONE question: which line is this
metric?

Design (each point is a guarantee, not a hope):
- The LLM returns a LINE ID, never a number. The value is read from that line
  by the same code the rules use, so the LLM cannot invent a figure that isn't
  printed on the page. Worst case it picks the wrong line.
- A wrong line is caught by the accounting identities. A proposal is accepted
  only if its metric comes out VERIFIED by a check that includes at least one
  RULE-extracted value. Two LLM picks agreeing only with each other don't count.
- A proposal must not break anything: if adding it would FLAG a value the rules
  had already found, it is dropped.
- Accepted values are VERIFIED with source "llm", so every receipt shows how the
  number was found. An unchecked LLM value is never shown, not even as PROBABLE.
- Off by default. No provider configured -> the pipeline behaves exactly as
  before. Any LLM error -> the metric stays MISSING; the run never fails.

Config (environment):
    FINAGENT_LLM_PROVIDER   gemini | groq        (unset = fallback off)
    GEMINI_API_KEY / GROQ_API_KEY
    FINAGENT_LLM_MODEL      optional model override
"""

import json
import os
import urllib.request

from .normalizer import item_values
from .schema import METRICS
from .validator import CROSS_STATEMENT_CHECKS, IDENTITY_CHECKS, Status, Validator

LLM_SOURCE = "llm"
STATEMENT_NAMES = {
    "BS": "balance sheet",
    "PL": "profit and loss statement",
    "CF": "cash flow statement",
}

# check name -> every metric that takes part in it
_CHECK_MEMBERS = {name: set(lhs) | set(rhs) | set(opt) for name, lhs, rhs, opt in IDENTITY_CHECKS}
_CHECK_MEMBERS.update({name: {a, b} for name, a, b in CROSS_STATEMENT_CHECKS})


# ---------------------------------------------------------------------------
# The model, behind a one-method interface (tests inject a fake)
# ---------------------------------------------------------------------------
def build_prompt(metric, statement, lines):
    hints = ", ".join(f'"{s}"' for s in METRICS[metric].get("synonyms", [])[:4])
    numbered = "\n".join(
        f"[{i}] {label} | {' | '.join(vals)}" for i, (label, vals) in enumerate(lines)
    )
    return (
        f"These are the lines of a company's {STATEMENT_NAMES[statement]} "
        f"(label | numbers, current year first).\n\n{numbered}\n\n"
        f"Which ONE line is the metric `{metric}` (usually labelled like {hints})? "
        "Labels may carry roman numerals, formula suffixes like (VII-VIII), or typos. "
        "If the report splits continuing and discontinued operations, prefer the total "
        "for the whole year. If no line clearly is this metric, answer null. "
        'Reply with JSON only: {"line_id": <integer or null>}'
    )


def parse_line_id(text, n_lines):
    """Model output -> a valid line index, or None. Anything malformed is None."""
    try:
        line_id = json.loads(text).get("line_id")
    except (ValueError, AttributeError):
        return None
    if isinstance(line_id, bool) or not isinstance(line_id, int):
        return None
    return line_id if 0 <= line_id < n_lines else None


def _post_json(url, payload, headers, timeout=30):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class GeminiChooser:
    def __init__(self, api_key, model=None):
        self.api_key, self.model = api_key, model or "gemini-2.5-flash"

    def choose(self, metric, statement, lines):
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": build_prompt(metric, statement, lines)}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {"line_id": {"type": "INTEGER", "nullable": True}},
                    "required": ["line_id"],
                },
            },
        }
        out = _post_json(url, payload, {})
        text = out["candidates"][0]["content"]["parts"][0]["text"]
        return parse_line_id(text, len(lines))


class GroqChooser:
    def __init__(self, api_key, model=None):
        self.api_key, self.model = api_key, model or "llama-3.3-70b-versatile"

    def choose(self, metric, statement, lines):
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": build_prompt(metric, statement, lines)}],
        }
        out = _post_json(
            "https://api.groq.com/openai/v1/chat/completions",
            payload,
            {"Authorization": f"Bearer {self.api_key}"},
        )
        return parse_line_id(out["choices"][0]["message"]["content"], len(lines))


def chooser_from_env():
    """The configured chooser, or None (fallback off)."""
    provider = os.getenv("FINAGENT_LLM_PROVIDER", "").strip().lower()
    model = os.getenv("FINAGENT_LLM_MODEL") or None
    if provider == "gemini" and os.getenv("GEMINI_API_KEY"):
        return GeminiChooser(os.environ["GEMINI_API_KEY"], model)
    if provider == "groq" and os.getenv("GROQ_API_KEY"):
        return GroqChooser(os.environ["GROQ_API_KEY"], model)
    return None


# ---------------------------------------------------------------------------
# Propose -> verify -> accept
# ---------------------------------------------------------------------------
def _validate(observations, candidates, expected):
    v = Validator(expected_metrics=expected)
    for metric, value, source, page, label in observations:
        v.add(metric, value, source=source, page=page, label_text=label)
    for metric, (value, page, label) in candidates.items():
        v.add(metric, value, source=LLM_SOURCE, page=page, label_text=label)
    return v.validate()


def _proven_by_rules(verdict, rule_metrics):
    """VERIFIED by at least one check that involves a rule-extracted value."""
    if verdict.status != Status.VERIFIED:
        return False
    for detail in verdict.checks_passed:
        members = _CHECK_MEMBERS.get(detail.split(" (")[0], set())
        if (members - {verdict.metric}) & rule_metrics:
            return True
    return False


def fill_missing(observations, raw_by_statement, expected, chooser, log=print):
    """Try to fill MISSING metrics. Returns (ValidationReport, accepted) where
    accepted maps metric -> (value, page, label) for every proposal kept.

    observations: [(metric, value, source, page, label)] from the rules
    raw_by_statement: {"BS"/"PL"/"CF": [RawItem, ...]} lines of located pages
    """
    baseline = _validate(observations, {}, expected)
    if chooser is None:
        return baseline, {}

    rule_metrics = {m for m, *_ in observations}
    used_labels = {label for *_, label in observations}
    candidates = {}
    for code, items in raw_by_statement.items():
        lines = [(it, item_values(it)) for it in items if it.label not in used_labels]
        lines = [(it, vals) for it, vals in lines if vals]
        if not lines:
            continue
        shown = [(it.label, [f"{v:,.2f}" for v in vals]) for it, vals in lines]
        for metric in expected:
            if METRICS[metric]["statement"] != code:
                continue
            if baseline.verdicts[metric].status != Status.MISSING:
                continue
            try:
                line_id = chooser.choose(metric, code, shown)
            except Exception as e:  # noqa: BLE001 — a model failure must never fail the run
                log(f"[llm] {metric}: provider error ({e.__class__.__name__}), stays MISSING")
                continue
            if line_id is None:
                continue
            item, vals = lines[line_id]
            candidates[metric] = (vals[0], item.page, item.label)
            log(f"[llm] {metric}: proposed line '{item.label}' = {vals[0]:,.2f}")

    # Drop unproven proposals until the set is stable: removing one proposal can
    # change which others still verify.
    while candidates:
        report = _validate(observations, candidates, expected)
        rejected = [m for m in candidates if not _proven_by_rules(report.verdicts[m], rule_metrics)]
        if not rejected:
            break
        for m in rejected:
            log(f"[llm] {m}: rejected, no accounting identity confirms it")
            del candidates[m]
    if not candidates:
        return baseline, {}

    # Never let a proposal break a value the rules had already found.
    report = _validate(observations, candidates, expected)
    newly_flagged = [
        m
        for m in rule_metrics
        if report.verdicts[m].status == Status.FLAGGED
        and baseline.verdicts[m].status != Status.FLAGGED
    ]
    if newly_flagged:
        log(f"[llm] proposals would flag rule values {newly_flagged}; all rejected")
        return baseline, {}
    for m in candidates:
        log(f"[llm] {m}: ACCEPTED, verified by accounting identity")
    return report, candidates
