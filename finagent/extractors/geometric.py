"""Geometric extractor: pdfplumber, line-based.

Financial statements are usually borderless, so instead of table detection
we reconstruct text lines from word coordinates and parse each line as
"label ... numbers". The first number on a line is treated as the
current-year value (leftmost value column); the rest are kept for later.

Physical pages are first run through the geometry stage: a two-up A3 page
becomes two logical pages, otherwise merged lines would read
"label-from-left-page numbers-from-right-page".

Output is raw: (label, value_strings, page). Parsing/normalising the
numbers is the normalizer's job.
"""

import re
from dataclasses import dataclass

import pdfplumber

from .. import geometry

# tokens that look like report numbers: 1,49,982.45  (1,234)  123.45  -
NUM_CHARS = set("0123456789,().%-−–—")

# European reports render negatives as a DETACHED minus: "− 112,858" is two
# words. Only unicode minuses get merged — a standalone ASCII "-" is a nil
# placeholder in Indian reports and must stay a separate token.
MINUS_TOKENS = {"−", "–", "—"}

# a real sign hugs its number; a nil placeholder ("−" meaning zero) sits in
# its own column, far from the next number
MAX_SIGN_GAP = 4.0

# standalone dashes are nil values: part of a row's numeric tail
PLACEHOLDER_TOKENS = {"-", "−", "–", "—"}

# A 4-digit period header ("2025", "(2024)") used to confirm we found the
# column-header row and to count the value columns.
YEAR_RE = re.compile(r"\(?(?:19|20)\d{2}\)?$")
# the reference-column header word ("Note", "Schedule", "Page" ...) — the
# value columns sit to its right, so its right edge is the column boundary.
REF_HEADER_RE = re.compile(r"^(?:notes?|schedule|sch|page|ref)\.?$", re.IGNORECASE)
# small gap to the right of the reference header before the value columns
REF_FLOOR_MARGIN = 12.0
# more year columns than this means a segmented sheet (BMW: a 2025/2024 pair
# per business segment) or a multi-year overview. The value column is then no
# longer simply "the leftmost", so positional cutting is unsafe — bail out.
MAX_VALUE_COLS = 3


@dataclass
class RawItem:
    label: str
    values: list  # raw strings, left to right
    page: int  # 0-based physical page
    source: str = "geometric"
    side: str = None  # current / non-current, from the enclosing BS section


def _is_numeric_token(tok):
    t = tok.strip()
    if not t or not any(c.isdigit() for c in t):
        return False
    return all(c in NUM_CHARS for c in t)


def _merge_detached_minus(line):
    """x0-sorted words -> [(token, x0)], gluing a detached minus onto the
    number it signs. Distance decides sign vs nil placeholder. The x0 (left
    edge) rides along so a token can later be assigned to its column."""
    out, i = [], 0
    while i < len(line):
        w = line[i]
        if (
            w["text"] in MINUS_TOKENS
            and i + 1 < len(line)
            and _is_numeric_token(line[i + 1]["text"])
            and line[i + 1]["x0"] - w["x1"] <= MAX_SIGN_GAP
        ):
            out.append(("-" + line[i + 1]["text"], w["x0"]))
            i += 2
        else:
            out.append((w["text"], w["x0"]))
            i += 1
    return out


def _detect_value_floor(lines):
    """Locate the left boundary of the value columns.

    Returns an x-coordinate: any number whose left edge sits below it is a
    reference-column entry (note / schedule / page number), not a value.
    Returns None when no confident header is found — callers then fall back to
    the magnitude heuristics.

    Two anchors. First the period-header row (the line with the most 4-digit
    year tokens) tells us where the value columns START (leftmost year) and how
    MANY there are — too many means a segmented/multi-year sheet (BMW prints a
    2025/2024 pair per business segment) where the value column isn't simply
    "leftmost", so we bail. Then the boundary itself is taken from the
    reference-column header word ("Note"/"Schedule"/"Page") sitting left of the
    values: its right edge is exactly where the value columns begin. Anchoring
    on the ref header beats anchoring on the year token, which can drift far
    right inside a wide "As at March 31, 2025" header while the numbers below
    align further left (BHEL).
    """
    xs = [w["x0"] for ln in lines for w in ln]
    if not xs or max(xs) - min(xs) < 50:  # no real column spread
        return None
    best = None  # (year_count, leftmost_year_x0)
    for ln in lines:
        yrs = [w["x0"] for w in ln if YEAR_RE.fullmatch(w["text"])]
        if not yrs:
            continue
        cand = (len(yrs), min(yrs))  # most years wins; tie -> rightmost
        if best is None or cand > best:
            best = cand
    if best is None or best[0] > MAX_VALUE_COLS:
        return None
    anchor = best[1]  # leftmost value-year column
    # rightmost reference-column header that sits left of the value columns
    ref_x1 = None
    for ln in lines:
        for w in ln:
            if REF_HEADER_RE.match(w["text"]) and w["x1"] < anchor:
                ref_x1 = w["x1"] if ref_x1 is None else max(ref_x1, w["x1"])
    if ref_x1 is None:  # no reference column to strip
        return None
    return ref_x1 + REF_FLOOR_MARGIN


def _lines_from_words(words, y_tol=2.5):
    """Group words into visual lines by their vertical position."""
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][-1]["top"]) <= y_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def _detect_column_bases(lines):
    """Scan header lines for column-spanning basis declarations ('Standalone' vs 'Consolidated').

    Returns a list of dicts: [{'basis': 'standalone', 'x0': float, 'x1': float}, ...] or empty list.
    """
    ranges = []
    for line in lines[:12]:
        text_line = " ".join(w["text"] for w in line).lower()
        if "standalone" in text_line or "consolidated" in text_line or "separate" in text_line or "group" in text_line:
            for w in line:
                t = w["text"].lower()
                if re.search(r"standalone|\bseparate\b", t):
                    ranges.append({"basis": "standalone", "x0": w["x0"], "x1": w["x1"] + 150})
                elif re.search(r"consolidated|\bgroup\b", t):
                    ranges.append({"basis": "consolidated", "x0": w["x0"], "x1": w["x1"] + 150})
    if not ranges:
        return []
    ranges.sort(key=lambda r: r["x0"])
    for i in range(len(ranges) - 1):
        mid = (ranges[i]["x1"] + ranges[i + 1]["x0"]) / 2
        ranges[i]["x1"] = mid
        ranges[i + 1]["x0"] = mid
    if ranges:
        ranges[0]["x0"] = 0.0
        ranges[-1]["x1"] = 9999.0
    return ranges


def _items_from_words(words, page_index, want_basis=None):
    items = []
    section = None
    side = None  # current / non-current: duplicate labels ("- Trade
    # receivables") appear under both BS sections
    side_heading = None  # text of the line that set the side; an
    # UNLABELED numeric row ENDING its block is the
    # section subtotal (Airtel prints "4,467,716
    # 3,862,549" with no label at all)
    pending = None  # candidate subtotal: only real if no labeled row
    # follows it before the block closes (a subtotal
    # is the LAST row of its section, so a mid-block
    # orphan from a wrapped label is discarded)
    prev_text = None  # immediately-preceding text-only line: a numeric
    # row whose label starts lowercase is its WRAPPED
    # continuation ("Profit for the year, representing
    # total" + "comprehensive income ... 419,056")

    def flush_pending():
        nonlocal pending
        if pending:
            items.append(pending)
            pending = None

    lines = _lines_from_words(words)
    # locate the value columns once for the whole block; None falls back to
    # the normalizer's magnitude heuristics (header not confidently found)
    value_floor = _detect_value_floor(lines)
    basis_ranges = _detect_column_bases(lines) if want_basis else []
    for line in lines:
        line.sort(key=lambda w: w["x0"])
        toks = _merge_detached_minus(line)  # [(text, x0), ...]
        texts = [t for t, _ in toks]
        # split into label prefix and trailing numeric tokens; nil
        # placeholders are tail members, not label text
        split = len(toks)
        for i in range(len(toks) - 1, -1, -1):
            if _is_numeric_token(texts[i]) or texts[i] in PLACEHOLDER_TOKENS:
                split = i
            else:
                break
        label = " ".join(texts[:split]).strip()
        num_pairs = toks[split:]
        # a parenthetical can split across the boundary: "... (refer note"
        # | "15)" — the closing fragment looks numeric and would become the
        # value (closing_cash = 15!). Re-join it into the label.
        while (
            label.count("(") > label.count(")")
            and num_pairs
            and re.fullmatch(r"[^()]*\)", num_pairs[0][0])
        ):
            label = f"{label} {num_pairs.pop(0)[0]}"
        # COLUMN GEOMETRY: a numeric token sitting LEFT of the leftmost value
        # column is a reference-column entry (note / schedule / page number),
        # not a value — drop it by POSITION, regardless of magnitude. This is
        # what lets a bare small integer ("5") under a year header be read as
        # a value. Guarded: if the filter would wipe out every number (header
        # mis-detected for this row), keep the row and let the magnitude
        # heuristics in the normalizer handle it.
        if value_floor is not None:
            kept = [p for p in num_pairs if p[1] >= value_floor]
            if kept:
                num_pairs = kept

        if want_basis and basis_ranges:
            matching = [r for r in basis_ranges if r["basis"] == want_basis]
            if matching:
                filtered = [p for p in num_pairs if any(r["x0"] <= p[1] <= r["x1"] for r in matching)]
                if filtered:
                    num_pairs = filtered

        nums = [t for t, _ in num_pairs]
        if label and nums:
            if prev_text and label[:1].islower():
                label = f"{prev_text} {label}"
            prev_text = None
            # bank/RBI-format statements label section totals just "Total"
            # (and EPS rows just "Basic"/"Diluted" under their heading);
            # qualify with the section heading ("ASSETS" -> "total assets")
            # so the normalizer can match it. A misattributed section simply
            # fails the fuzzy threshold and the row stays unmatched.
            if section and re.fullmatch(r"(total|basic|diluted):?", label, re.IGNORECASE):
                label = f"{label.rstrip(':')} {section}"
            # a total-ish row ("TOTAL LIABILITIES", "NET CURRENT ASSETS")
            # closes the block — totals FOLLOW subtotals, so a pending
            # unlabeled row right before it IS the subtotal (Wilmar).
            # Any other labeled row means the pending row wasn't the
            # block's last — a wrapped-label orphan, discarded.
            if re.match(r"(total|net)\b", label, re.IGNORECASE):
                flush_pending()
            else:
                pending = None
            if re.match(r"total\b", label, re.IGNORECASE):
                side_heading = None
            items.append(RawItem(label=label, values=nums, page=page_index, side=side))
        elif nums and side_heading:
            prev_text = None
            # unlabeled numeric row inside a current/non-current block:
            # candidate subtotal (last one wins). A wrong synthesis either
            # fails the fuzzy gate (absence), loses the first-wins tie to
            # the real row, or breaks a composition identity (FLAGGED).
            pending = RawItem(
                label=f"total {side_heading}", values=nums, page=page_index, side=side
            )
        elif label:
            flush_pending()  # a heading closes the block: the pending
            # unlabeled row WAS its last row = subtotal
            prev_text = label
            # a text-only line is a section heading candidate; strip leading
            # roman/decimal numbering ("I. INCOME" -> "income") and heading
            # parentheticals, which are unit/face-value noise ("EARNINGS PER
            # EQUITY SHARE (Face value 1/- per share)")
            section = re.sub(
                r"^[\divxlc]+[.)]\s*", "", re.sub(r"\([^)]*\)", " ", label.lower())
            ).strip()
            # "non-current" contains "current": test it first. Headings that
            # mention neither leave the side untouched ("Financial assets").
            if re.search(r"non[- ]current", section):
                side = "non-current"
                side_heading = section
            elif "current" in section:
                side = "current"
                side_heading = section
    flush_pending()
    return items


def _matches_statement(words, cue_pats):
    """Does this logical half belong to the statement we were sent to?

    Threshold is 1 cue, not 2: the locator already vouched for the page, so
    the half-picker only needs to drop the OTHER statement sharing an A3
    two-up sheet. A statement can SPAN both halves (Airtel CF: financing
    section alone on the right half, exactly 1 cue) — requiring 2 cues
    silently discarded it."""
    text = " ".join(w["text"] for w in words).lower()
    return sum(1 for p in cue_pats if re.search(p, text)) >= 1


def extract(pdf_path, page_indices, cue_pats=None, want_basis=None):
    """Extract raw line items from the given 0-based physical pages.

    cue_pats: content cues of the target statement. Used only to pick the
    right half of a split two-up page; if no half matches, keep all (the
    normalizer's allowed-metrics filter is the second line of defence).
    want_basis: optional 'standalone' or 'consolidated' filter for multi-column tables.
    """
    items = []
    with pdfplumber.open(pdf_path) as pdf:
        for idx in page_indices:
            if not (0 <= idx < len(pdf.pages)):
                continue
            page = pdf.pages[idx]
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            # rotated words are page furniture (vertical "Financial
            # Statements" tabs) that share a y-band with table rows and
            # break the numeric-tail scan. On a landscape page EVERYTHING
            # is rotated — there the filter must stand down.
            upright = [w for w in words if w.get("upright", True)]
            if len(upright) >= len(words) / 2:
                words = upright
            logical = geometry.logical_pages(page, words)
            if len(logical) > 1 and cue_pats:
                matching = [g for g in logical if _matches_statement(g, cue_pats)]
                logical = matching or logical
            for group in logical:
                items.extend(_items_from_words(group, idx, want_basis=want_basis))
    return items

