"""Stage 3: find and classify the statement pages.

Keyword scoring over the profiler's per-page text. For each statement type
we want the CONSOLIDATED version; fall back to standalone if the document
has no consolidated statements (or doesn't say).
"""
import re
from dataclasses import dataclass

# What counts as a "money figure" when deciding a page carries a real
# statement (not a ToC mention). Two shapes: a long comma-grouped integer
# ("1,58,788") OR a decimal figure with two places ("8207.65"). The decimal
# shape is essential for reports printed in crore, where consolidated line
# items are small 4-digit decimals that the comma-grouped pattern misses
# entirely — BHEL's whole P&L scored 0 on the integer-only count.
NUM_RE = re.compile(r"\d[\d,]{4,}|\d[\d,]*\.\d{2}\b")

# (title patterns, content cue patterns) — title hits score heavily,
# cues confirm we're on the statement itself rather than a ToC mention.
STATEMENT_SIGNATURES = {
    "BS": (
        [r"balance sheet", r"statement of financial position"],
        # second row: bank wording (Banking Regulation Act Schedule III) —
        # banks print Capital and Liabilities / Deposits / Advances with no
        # current/non-current split, so corporate cues never fire
        [r"total assets", r"equity and liabilities", r"total equity",
         r"non[- ]current assets", r"current liabilities",
         r"capital and liabilities", r"reserves and surplus",
         r"\bdeposits\b", r"\badvances\b", r"\bborrowings\b"],
    ),
    "PL": (
        # "profit AND loss" is Indian GAAP wording; IFRS reports (Singapore,
        # EU) title the same statement "profit OR loss" / "comprehensive income"
        [r"statement of profit (?:and|or) loss", r"income statement",
         r"statement of (?:operations|income)", r"profit and loss account",
         r"statement of comprehensive income"],
        [r"revenue from operations", r"total income", r"profit before tax",
         r"earnings per (?:equity )?share", r"total expenses",
         r"gross profit", r"cost of sales", r"profit for the year",
         r"income tax expense"],
    ),
    "CF": (
        [r"(?:statement of )?cash flows?", r"cash flow statement"],
        [r"operating activities", r"investing activities", r"financing activities"],
    ),
}


@dataclass
class Location:
    statement: str       # BS / PL / CF
    basis: str           # consolidated / standalone / unknown
    page_indices: list   # 0-based, best first
    score: float


def _search(pat, text):
    """re.search with a kerning-tolerant fallback: PDF text layers sometimes
    split a word internally ("BAL ANCE SHEET"), so retry with the pattern's
    literal spaces removed against space-collapsed text."""
    return (re.search(pat, text)
            or re.search(pat.replace(" ", ""), text.replace(" ", "")))


def _is_heading(line, title_pats):
    """True if `line` is a statement HEADING (the title phrase starts at its
    head, after at most a 2-word basis/company prefix) rather than a prose
    mention that merely contains the phrase. Kerning-split titles ("BAL ANCE
    SHEET") count as headings — they only arise on real heading lines."""
    for p in title_pats:
        m = re.search(p, line)
        if m:
            if len(line[:m.start()].split()) <= 2:
                return True
        elif re.search(p.replace(" ", ""), line.replace(" ", "")):
            return True
    return False


def _score_page(text, title_pats, cue_pats):
    t = text.lower()
    title = sum(3 for p in title_pats if _search(p, t))
    cues = sum(1 for p in cue_pats if re.search(p, t))
    if title == 0 or cues < 2:
        return 0, "unknown", False
    # ToC pages mention many statements but have few numbers
    numbers = len(NUM_RE.findall(t))
    if numbers < 8:
        return 0, "unknown", False
    # a real statement carries its title as a top-of-page heading; commentary
    # pages (management report) merely mention the statement in prose
    head_lines = [ln.strip() for ln in t.strip().splitlines()[:6] if ln.strip()]
    # a TITLE is a heading line whose statement phrase sits at the HEAD of the
    # line, optionally after a short basis/company prefix ("Standalone Balance
    # Sheet", "BMW AG Balance Sheet", "Balance Sheet for Group and Segments at
    # 31 December 2025"). A prose sentence buries the phrase mid-line
    # ("Provisions are reviewed at each balance sheet date ..." on a notes
    # page) — that is NOT a title. Without this guard a notes sentence becomes
    # a fake heading, takes the +5 boost and a basis stamp, and outranks the
    # real statement. Length alone fails (dated titles run to ~10 words);
    # position is the discriminator: phrase must start within the first 2 words.
    title_line = next((ln for ln in head_lines
                       if _is_heading(ln, title_pats)), None)
    # "Condensed/Summarised X" headings are management-report summaries,
    # not the statement itself — no heading boost, no basis authority
    if title_line and re.search(r"condensed|summaris|summariz|abridged",
                                title_line):
        title_line = None
    # real statements show two comparative periods (IAS 1); a page parading
    # many distinct years is a ten-year/multi-year overview. Heading-titled
    # pages get slack — footnotes legitimately cite years (Airtel's spectrum
    # auction list) — pages without a true heading do not
    years = {m for m in re.findall(r"\b(?:19|20)\d{2}\b", t)}
    if len(years) >= (10 if title_line else 6):
        return 0, "unknown", False
    if title_line:
        title += 5
    # the title line declares the basis ("Consolidated Balance Sheet",
    # German "for Group and Segments"); whole-page text is only a fallback —
    # running headers/prose mentioning "group"/"consolidated" must not count
    basis = "unknown"
    if title_line and re.search(r"consolidated|\bgroup\b", title_line):
        basis = "consolidated"
    elif title_line and re.search(r"standalone|\bseparate\b", title_line):
        basis = "standalone"
    elif "consolidated" in t:
        basis = "consolidated"
    elif "standalone" in t or "separate financial" in t:
        basis = "standalone"
    return title + cues + min(numbers, 30) * 0.1, basis, bool(title_line)


def locate(doc_profile):
    """Return {statement_code: Location} for BS, PL, CF."""
    results = {}
    for code, (title_pats, cue_pats) in STATEMENT_SIGNATURES.items():
        scored = []  # (score, basis, heading, index)
        for p in doc_profile.pages:
            if p.text_quality == "EMPTY":
                continue
            s, basis, heading = _score_page(p.text, title_pats, cue_pats)
            if s > 0:
                scored.append((s, basis, heading, p.index))
        if not scored:
            results[code] = Location(code, "unknown", [], 0)
            continue
        # heading-titled pages are real statements; pages that merely
        # discuss the statement (notes, management report) rank below them —
        # a notes page saying "consolidated" must not hijack the basis pool
        headed = [x for x in scored if x[2]]
        pool = headed or scored
        # prefer consolidated pages within the tier, if any exist
        consolidated = [x for x in pool if x[1] == "consolidated"]
        pool = consolidated or pool
        # ties go to the EARLIER page: the statement itself precedes the
        # notes/SOCIE pages that echo its keywords
        pool.sort(key=lambda x: (-x[0], x[3]))
        score, basis, _, best = pool[0]
        # Statements may continue on a neighbouring page (which lacks the
        # title there). Only adjacent pages qualify — a distant page that
        # also scores is a DIFFERENT copy of the statement (standalone,
        # prior period, summary) and mixing it corrupts the metric set.
        pages = [best]
        for nb in (best - 1, best + 1):
            if 0 <= nb < doc_profile.n_pages and _is_continuation(
                    doc_profile.pages[nb].text, cue_pats):
                pages.append(nb)
        results[code] = Location(code, basis, pages, score)
    return results


def _is_continuation(text, cue_pats):
    t = text.lower()
    cues = sum(1 for p in cue_pats if re.search(p, t))
    numbers = len(NUM_RE.findall(t))
    return cues >= 1 and numbers >= 8
