"""Stage 5: normalize raw line items into canonical metrics.

- parse number strings (Indian/intl commas, (parens) negatives, dashes)
- drop note-reference columns ("Revenue from operations  24  1,49,982 ...")
- fuzzy-match label text to the canonical schema
"""
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .schema import METRICS

MATCH_THRESHOLD = 88


@dataclass
class Extraction:
    metric: str
    value: float
    raw_label: str
    page: int
    source: str
    score: float
    extra_values: list  # remaining columns (usually prior year)


def parse_number(tok):
    """'(1,234.5)' -> -1234.5 ; '1,49,982' -> 149982.0 ; '-' -> None"""
    t = tok.strip().rstrip("*#†")
    t = t.replace("−", "-").replace("–", "-").replace("—", "-")
    if not t or not any(c.isdigit() for c in t):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "").replace("%", "").strip()
    if t.startswith("-"):
        neg, t = True, t[1:]
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _looks_like_note_ref(tok, rest, label=""):
    """A bare small integer in the first numeric slot is a note-reference
    column, even when it is the ONLY number (a split table can leave the
    note ref behind while the value columns land elsewhere — taking it as
    the value would yield revenue=25). Real values carry commas, decimals,
    parens, or more digits."""
    # if the note ref was consumed into the label ("Inventories 10(e)"),
    # the first numeric token IS the value — dropping it took prior-year 28
    # over golden 21 (TCS)
    if re.search(r"\d[a-z()]*\s*$", label):
        return False
    t = tok.strip()
    if re.fullmatch(r"\d{1,2}", t):
        return True
    # a 3-digit bare int is usually a value, not a note number (Airtel fx
    # effect 718); treat as note ref only with the ~100x jump a real
    # label->note->value row shows
    if re.fullmatch(r"\d{3}", t) and rest:
        nxt = parse_number(rest[0])
        return nxt is not None and abs(nxt) >= 100 * float(t)
    # decimal note refs exist too (Adani numbers notes "5.5"); only a note
    # ref when the next value is orders of magnitude larger — an EPS of
    # 8.05 followed by prior-year 10.20 must survive
    if re.fullmatch(r"\d{1,2}\.\d{1,2}", t) and rest:
        nxt = parse_number(rest[0])
        return nxt is not None and abs(nxt) >= 100 * float(t)
    return False


def _looks_like_page_ref(tok, nxt):
    """A SECOND leading reference column. Some statements (BHEL) print both a
    Note column AND a Page cross-ref column before the values:
    "Inventories | 10 | 289 | 9,869.49". The note ref (10) is stripped first;
    289 is the page where the note lives, not a value. The 3-digit jump rule in
    _looks_like_note_ref can't catch it (289 -> 9,869 is only ~34x), so it would
    be taken as inventories=289. Safe signature: only fires once a note ref has
    already been stripped (single-reference tables never reach here), the token
    is a bare 1-3 digit integer, and a real money figure (comma or decimal)
    follows it — a page ref always precedes the value columns."""
    t = tok.strip()
    if not re.fullmatch(r"\d{1,3}", t):
        return False
    n = (nxt or "").strip()
    return bool(re.search(r"[.,]", n)) and parse_number(n) is not None


# sign/unit/reference qualifiers carry no identity — "/(loss)", "/loss",
# "(used in)", "(decrease)", "(in rupees)", "(note 24)", "(net of refunds)" —
# and are stripped from labels AND synonyms alike. Classification qualifiers
# ("(non-current)", "(current)") DO carry identity and must survive: stripping
# them once let the non-current line shadow the real value (TCS/Adani/Airtel
# golden WRONGs), because both then clean to the same string and the
# non-current section comes first.
# bare "(net)" is NOT a qualifier here: stripping it turned "Current tax
# liabilities (net)" into a 92-score match for total current liabilities
_QUALIFIER = (r"(?:loss(?:es)?|decrease|used in|in rupees|rs\.?|"
              r"net of [^)]*|refer[^)]*|notes?\s*[\d., ]*|continued|"
              r"face value[^)]*|"          # (Face Value of Rs 10 each)
              r"[a-z](?:\s*\+\s*[a-z])*)")  # cross-refs: (a), (a+b+c)


def clean_label(label):
    t = label.lower()
    t = re.sub(rf"/\s*\(?{_QUALIFIER}\)?(?=[\s)]|$)", " ", t)  # /(loss), /loss
    t = re.sub(rf"\(\s*{_QUALIFIER}\s*\)", " ", t)             # (used in)
    t = re.sub(r"^[\divxlc]+[.)]\s*", "", t)          # leading numbering: 1. / (iv)
    # fully-parenthesized enumerators: "(ii) Trade Receivables", "(a) …"
    t = re.sub(r"^\((?:[ivxlc]{1,4}|[a-z]|\d{1,2})\)\s*", "", t)
    # a LEADING basis word is page-level info the locator already resolved
    # ("Consolidated Net Profit for the year..."), not label identity
    t = re.sub(r"^(?:consolidated|standalone)\s+", "", t)
    t = re.sub(r"[^a-z()/'& -]", " ", t)              # drop stray digits/symbols
    return re.sub(r"\s+", " ", t).strip()


def _cleaned_synonyms():
    return {metric: sorted({clean_label(s) for s in spec["synonyms"]})
            for metric, spec in METRICS.items()}


CLEANED_SYNONYMS = _cleaned_synonyms()


def match_label(label):
    """Return (metric, score) or (None, 0)."""
    t = clean_label(label)
    if len(t) < 3:
        return None, 0
    best, best_score, best_syn = None, 0, ""
    for metric, syns in CLEANED_SYNONYMS.items():
        for syn in syns:
            s = fuzz.token_sort_ratio(t, syn)
            if s > best_score:
                best, best_score, best_syn = metric, s, syn
    if best_score >= MATCH_THRESHOLD:
        # an "Other …" line is a residual, not the total it resembles:
        # "Other current liabilities" must not satisfy current_liabilities
        if t.startswith("other ") and "other" not in best_syn:
            return None, 0
        # directional qualifiers are identity, not noise: "net profit AFTER
        # minority interest" scores 92 against the "... BEFORE minority
        # interest" synonym — a one-token swap the threshold can't separate
        lt, st = set(t.split()), set(best_syn.split())
        if ({"before", "after"} & lt) and ({"before", "after"} & st) \
                and ("before" in lt) != ("before" in st):
            return None, 0
        return best, best_score
    return None, 0


def _label_matches(label):
    """All (metric, score) readings of a label. An appositive label —
    "Profit for the year, representing total comprehensive income for the
    year" (Newgen) — names the SAME number twice; both parts are matched
    so one line can satisfy two metrics."""
    t = clean_label(label)
    if " representing " in t:
        parts = [match_label(p) for p in t.split(" representing ")]
        matches = [(m, s) for m, s in parts if m]
        if matches:
            return matches
    m, s = match_label(label)
    return [(m, s)] if m else []


def normalize(raw_items, allowed_metrics=None):
    """RawItems -> best Extraction per canonical metric."""
    by_metric = {}
    for item in raw_items:
        for metric, score in _label_matches(item.label):
            if allowed_metrics is not None and metric not in allowed_metrics:
                continue
            # duplicate labels under both BS sections ("- Trade
            # receivables"): a current-side metric must not take the
            # non-current section's row. A wrong veto degrades to MISSING,
            # never to a wrong value.
            want_side = METRICS[metric].get("side")
            if want_side and getattr(item, "side", None) not in (None, want_side):
                continue
            toks = list(item.values)
            note_stripped = False
            if toks and _looks_like_note_ref(toks[0], toks[1:], item.label):
                toks = toks[1:]
                note_stripped = True
            # second reference column: a Page cross-ref (Note + Page columns,
            # BHEL). Only after a note ref was stripped — the double-column
            # signature — so single-reference statements are untouched.
            if note_stripped and len(toks) >= 2 and _looks_like_page_ref(
                    toks[0], toks[1]):
                toks = toks[1:]
            values = [parse_number(t) for t in toks]
            values = [v for v in values if v is not None]
            if not values:
                continue
            ext = Extraction(metric=metric, value=values[0],
                             raw_label=item.label, page=item.page,
                             source=item.source, score=score,
                             extra_values=values[1:])
            prev = by_metric.get(metric)
            if prev is None or score > prev.score:
                by_metric[metric] = ext
    return by_metric
