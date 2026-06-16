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


@dataclass
class RawItem:
    label: str
    values: list      # raw strings, left to right
    page: int         # 0-based physical page
    source: str = "geometric"
    side: str = None  # current / non-current, from the enclosing BS section


def _is_numeric_token(tok):
    t = tok.strip()
    if not t or not any(c.isdigit() for c in t):
        return False
    return all(c in NUM_CHARS for c in t)


def _merge_detached_minus(line):
    """x0-sorted words -> token strings, gluing a detached minus onto the
    number it signs. Distance decides sign vs nil placeholder."""
    out, i = [], 0
    while i < len(line):
        w = line[i]
        if (w["text"] in MINUS_TOKENS and i + 1 < len(line)
                and _is_numeric_token(line[i + 1]["text"])
                and line[i + 1]["x0"] - w["x1"] <= MAX_SIGN_GAP):
            out.append("-" + line[i + 1]["text"])
            i += 2
        else:
            out.append(w["text"])
            i += 1
    return out


def _lines_from_words(words, y_tol=2.5):
    """Group words into visual lines by their vertical position."""
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][-1]["top"]) <= y_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def _items_from_words(words, page_index):
    items = []
    section = None
    side = None   # current / non-current: duplicate labels ("- Trade
                  # receivables") appear under both BS sections
    side_heading = None   # text of the line that set the side; an
                          # UNLABELED numeric row ENDING its block is the
                          # section subtotal (Airtel prints "4,467,716
                          # 3,862,549" with no label at all)
    pending = None        # candidate subtotal: only real if no labeled row
                          # follows it before the block closes (a subtotal
                          # is the LAST row of its section, so a mid-block
                          # orphan from a wrapped label is discarded)
    prev_text = None      # immediately-preceding text-only line: a numeric
                          # row whose label starts lowercase is its WRAPPED
                          # continuation ("Profit for the year, representing
                          # total" + "comprehensive income ... 419,056")

    def flush_pending():
        nonlocal pending
        if pending:
            items.append(pending)
            pending = None

    for line in _lines_from_words(words):
        line.sort(key=lambda w: w["x0"])
        toks = _merge_detached_minus(line)
        # split into label prefix and trailing numeric tokens; nil
        # placeholders are tail members, not label text
        split = len(toks)
        for i in range(len(toks) - 1, -1, -1):
            if _is_numeric_token(toks[i]) or toks[i] in PLACEHOLDER_TOKENS:
                split = i
            else:
                break
        label = " ".join(toks[:split]).strip()
        nums = toks[split:]
        # a parenthetical can split across the boundary: "... (refer note"
        # | "15)" — the closing fragment looks numeric and would become the
        # value (closing_cash = 15!). Re-join it into the label.
        while (label.count("(") > label.count(")") and nums
               and re.fullmatch(r"[^()]*\)", nums[0])):
            label = f"{label} {nums.pop(0)}"
        if label and nums:
            if prev_text and label[:1].islower():
                label = f"{prev_text} {label}"
            prev_text = None
            # bank/RBI-format statements label section totals just "Total"
            # (and EPS rows just "Basic"/"Diluted" under their heading);
            # qualify with the section heading ("ASSETS" -> "total assets")
            # so the normalizer can match it. A misattributed section simply
            # fails the fuzzy threshold and the row stays unmatched.
            if section and re.fullmatch(r"(total|basic|diluted):?", label,
                                        re.IGNORECASE):
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
            items.append(RawItem(label=label, values=nums, page=page_index,
                                 side=side))
        elif nums and side_heading:
            prev_text = None
            # unlabeled numeric row inside a current/non-current block:
            # candidate subtotal (last one wins). A wrong synthesis either
            # fails the fuzzy gate (absence), loses the first-wins tie to
            # the real row, or breaks a composition identity (FLAGGED).
            pending = RawItem(label=f"total {side_heading}", values=nums,
                              page=page_index, side=side)
        elif label:
            flush_pending()   # a heading closes the block: the pending
                              # unlabeled row WAS its last row = subtotal
            prev_text = label
            # a text-only line is a section heading candidate; strip leading
            # roman/decimal numbering ("I. INCOME" -> "income") and heading
            # parentheticals, which are unit/face-value noise ("EARNINGS PER
            # EQUITY SHARE (Face value 1/- per share)")
            section = re.sub(r"^[\divxlc]+[.)]\s*", "",
                             re.sub(r"\([^)]*\)", " ", label.lower())).strip()
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


def extract(pdf_path, page_indices, cue_pats=None):
    """Extract raw line items from the given 0-based physical pages.

    cue_pats: content cues of the target statement. Used only to pick the
    right half of a split two-up page; if no half matches, keep all (the
    normalizer's allowed-metrics filter is the second line of defence).
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
                items.extend(_items_from_words(group, idx))
    return items
