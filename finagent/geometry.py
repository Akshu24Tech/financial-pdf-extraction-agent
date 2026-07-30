"""Stage 2: geometry fixes — turn messy physical pages into clean logical pages.

Annual reports often print two logical pages side by side on one landscape
sheet (A3 two-up: Airtel, Reliance). Word lines then merge across the spine
and every downstream parse reads "label-from-left-page numbers-from-right-page".
We find the gutter and split the words into two logical pages.

A true single-page landscape table (BMW style) must NOT be split, so the
gutter test is conservative: an almost-empty vertical band, with substantial
text on both sides.
"""

GUTTER_BINS = 200  # x-axis resolution for the coverage histogram
SEARCH_LO, SEARCH_HI = 0.35, 0.65  # look for the gutter in the middle third
MAX_GUTTER_COVERAGE = 0.01  # words allowed to touch the gutter band
MIN_SIDE_RATIO = 0.2  # both halves must carry real text


def _gutter_x(page_width, words):
    """X position of the spine: the near-empty vertical band CLOSEST TO THE
    CENTRE (not the emptiest one — a table's gap between its label column
    and its number columns is often emptier than the true spine)."""
    cover = [0] * GUTTER_BINS
    for w in words:
        a = max(int(w["x0"] / page_width * GUTTER_BINS), 0)
        b = min(int(w["x1"] / page_width * GUTTER_BINS), GUTTER_BINS - 1)
        for i in range(a, b + 1):
            cover[i] += 1
    lo, hi = int(GUTTER_BINS * SEARCH_LO), int(GUTTER_BINS * SEARCH_HI)
    threshold = max(1, MAX_GUTTER_COVERAGE * len(words))
    candidates = [i for i in range(lo, hi) if cover[i] <= threshold]
    if not candidates:
        return None
    centre = GUTTER_BINS / 2
    best = min(candidates, key=lambda i: abs(i + 0.5 - centre))
    return (best + 0.5) / GUTTER_BINS * page_width


def split_two_up(page, words):
    """Return (left_words, right_words) if the page is two-up, else None."""
    if page.width <= page.height or len(words) < 20:
        return None
    gx = _gutter_x(page.width, words)
    if gx is None:
        return None
    left = [w for w in words if (w["x0"] + w["x1"]) / 2 <= gx]
    right = [w for w in words if (w["x0"] + w["x1"]) / 2 > gx]
    if min(len(left), len(right)) < MIN_SIDE_RATIO * max(len(left), len(right), 1):
        return None  # one side nearly empty: a wide table, not two pages
    for side in (left, right):
        alpha = sum(1 for w in side if any(c.isalpha() for c in w["text"]))
        if alpha < 0.3 * len(side):
            return None  # a side that is mostly numbers is a value-column
            # block of one wide table, not a logical page
    return left, right


def logical_pages(page, words):
    """One physical page -> list of logical word groups (1 or 2)."""
    halves = split_two_up(page, words)
    return list(halves) if halves else [words]


if __name__ == "__main__":
    import sys

    import pdfplumber

    if len(sys.argv) < 2:
        print("Usage: python -m finagent.geometry <pdf_path> [page_num_1based]")
        sys.exit(1)
    pdf_path = sys.argv[1]
    page_no = int(sys.argv[2]) - 1 if len(sys.argv) > 2 else 0
    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[page_no]
        words = p.extract_words()
        halves = split_two_up(p, words)
        if halves:
            left, right = halves
            print(
                f"Page {page_no + 1} is TWO-UP (A3 Split!): Left words = {len(left)}, Right words = {len(right)}"
            )
        else:
            print(
                f"Page {page_no + 1} is SINGLE LOGICAL PAGE (No split). Total words = {len(words)}"
            )
