# Architecture & Function Guide

A plain-language walkthrough of **how this project works** and **what every
function does**. Read the README first for the big picture; this file is the
deep dive you can use to explain any part of the code to anyone.

---

## Table of contents

1. [The mental model (read this first)](#1-the-mental-model)
2. [How data flows through the system](#2-how-data-flows)
3. [The data objects (what gets passed around)](#3-the-data-objects)
4. [Stage 1 — Profiler](#4-stage-1--profiler)
5. [Stage 2 — Geometry](#5-stage-2--geometry)
6. [Stage 3 — Locator](#6-stage-3--locator)
7. [Stage 4 — Extractor](#7-stage-4--extractor)
8. [Stage 5 — Normalizer](#8-stage-5--normalizer)
9. [Stage 6 — Validator](#9-stage-6--validator)
10. [Stage 6b — Deriver](#10-stage-6b--deriver)
11. [Stage 7 — Writer](#11-stage-7--writer)
12. [The Schema (shared vocabulary)](#12-the-schema)
13. [The Pipeline (glue)](#13-the-pipeline)
14. [Frequently asked "why"](#14-frequently-asked-why)

---

## 1. The mental model

Imagine you hand a stack of 600 pages to a careful accounting clerk and say
*"find me the key numbers."* A sloppy clerk reads numbers off the page and
hands them over. Our clerk is paranoid: **after reading a number, they prove
it's right by checking it against the other numbers.**

That paranoia is the whole design. Financial statements follow fixed rules
(Assets = Liabilities + Equity, etc.). If a number we read makes those rules
add up, we trust it. If it breaks a rule, we flag it instead of lying.

So the system has two halves:
- **Reading** (stages 1–5): get candidate numbers off the PDF.
- **Proving** (stages 6–6b): confirm them with maths, or flag them.

The reading half is allowed to be imperfect. The proving half is what makes
the output trustworthy.

---

## 2. How data flows

```
PDF file
   │
   │   profile()           "describe every page"
   ▼
DocProfile (list of PageProfile)
   │
   │   locate()            "which pages are the statements?"
   ▼
{BS: Location, PL: Location, CF: Location}
   │
   │   extract()           "read those pages into raw rows"
   ▼                       (uses logical_pages() to split two-up sheets)
list of RawItem (label + number-strings)
   │
   │   normalize()         "clean numbers, name each row"
   ▼
{metric: Extraction}
   │
   │   Validator.add() + validate()   "prove with accounting rules"
   ▼
ValidationReport (verdict per metric)
   │
   │   derive()            "compute what the rules pin down"
   ▼
ValidationReport (now with DERIVED values too)
   │
   │   write_excel()       "save with receipts"
   ▼
output/<Company>_metrics.xlsx
```

Each arrow is a function. Each box is a data object. The next two sections
explain both.

---

## 3. The data objects

These small classes are the "envelopes" passed between stages. Knowing them
makes every function obvious.

| Object | Lives in | Holds | Created by |
|---|---|---|---|
| `PageProfile` | profiler | one page's size, orientation, text, text-quality | `profile()` |
| `DocProfile` | profiler | the whole document = list of `PageProfile` | `profile()` |
| `Location` | locator | which pages a statement is on + its score/basis | `locate()` |
| `RawItem` | extractor | one table row: a label + its raw number-strings | `extract()` |
| `Extraction` | normalizer | one matched metric: clean value + where it came from | `normalize()` |
| `MetricVerdict` | validator | final verdict for one metric (status, value, checks) | `validate()` / `derive()` |
| `ValidationReport` | validator | all verdicts together, with summary/export helpers | `validate()` |

A useful way to say it: **RawItem is what we *read*, Extraction is what we
*understood*, MetricVerdict is what we *proved*.**

---

## 4. Stage 1 — Profiler

**File:** `finagent/profiler.py` · **Job:** describe the PDF page by page so
later stages know what they're dealing with. Uses `pypdf`, which is fast,
because this pass touches *every* page.

### `class PageProfile`
A plain record for one page: its `index` (0-based), `width`, `height`,
`landscape` (is it wider than tall?), the page's raw `text`, and
`text_quality` (`OK` / `SUSPECT` / `EMPTY`). Later stages read these instead
of re-opening the PDF.

### `class DocProfile`
The whole document. Holds the file `path`, `n_pages`, and the list of
`pages`. Two helpers:
- **`landscape_ratio`** — what fraction of pages are landscape. A high ratio
  hints the report is printed on wide A3 sheets (relevant to Stage 2).
- **`summary()`** — a one-line dict like `{pages: 60, landscape_ratio: 0.1,
  text_quality: {OK: 55, EMPTY: 5}}` for logging.

### `_quality(text)`
Grades a page's text. Logic in plain words:
- Less than 50 characters of text → `EMPTY` (probably a scanned image or a
  blank/cover page).
- Otherwise count the letters inside real words (3+ letters long). If letters
  make up more than 30% of the text → `OK`; if it's mostly digits and symbols
  → `SUSPECT` (a garbled text layer).

This matters because the locator skips `EMPTY` pages entirely.

### `profile(pdf_path)`  ← entry point
Opens the PDF and loops over every page:
1. Reads the page box to get `width`/`height`.
2. If the page is rotated 90°/270°, swaps width and height so "landscape"
   reflects how it actually looks.
3. Tries to extract the text (wrapped in `try/except` because some pages throw
   on bad encoding — we just treat those as empty).
4. Builds a `PageProfile` and appends it.

Returns one `DocProfile` describing the entire document.

---

## 5. Stage 2 — Geometry

**File:** `finagent/geometry.py` · **Job:** fix one specific physical-layout
problem before reading. Some reports (Airtel, Reliance) print **two logical
pages side by side on one wide A3 sheet** ("two-up"). If you read such a sheet
naively, each line becomes "label-from-the-left-page numbers-from-the-right-page"
— total garbage. This stage finds the spine and splits the sheet in two.

The tricky part: a genuinely *wide single table* (BMW's landscape balance
sheet) must **not** be split. So the test for "is this two pages?" is
deliberately strict.

### The constants
- `GUTTER_BINS = 200` — we slice the page width into 200 vertical strips to
  measure where text sits.
- `SEARCH_LO/HI = 0.35 / 0.65` — only look for the spine in the middle third
  of the page (a real two-up spine is near the centre).
- `MAX_GUTTER_COVERAGE = 0.01` — the spine strip must be nearly empty (≤1% of
  words touch it).
- `MIN_SIDE_RATIO = 0.2` — both halves must carry real text; if one side is
  nearly empty it's not two pages.

### `_gutter_x(page_width, words)`
Finds the **x-position of the spine** (the empty vertical band between the two
pages). Logic:
1. Build a coverage histogram: for each word, mark which of the 200 strips it
   spans. Strips with many words = dense text; strips with few = gaps.
2. Among the strips in the middle third that are nearly empty, pick the one
   **closest to the centre** — *not* the emptiest. (Why: a table's gap between
   its label column and its number columns can be emptier than the true spine.
   Centre-ness is the better signal.)
3. Convert that strip back to an x-coordinate and return it. Returns `None` if
   no near-empty middle band exists (so: not two-up).

### `split_two_up(page, words)`
Decides if a page is two-up and, if so, splits the words. Returns
`(left_words, right_words)` or `None`. Guard rails, in order:
1. If the page isn't landscape, or has fewer than 20 words → not two-up.
2. Find the gutter with `_gutter_x`. No gutter → `None`.
3. Split words into left/right by which side of the gutter their centre falls.
4. If one side has far less text than the other → it's a wide table, not two
   pages → `None`.
5. If either side is **mostly numbers** (less than 30% of its words contain a
   letter) → that "side" is just a block of value columns from one wide table,
   not a real page → `None`.

Only if all guards pass do we call it two-up.

### `logical_pages(page, words)`  ← entry point
The simple public wrapper: returns the two halves if `split_two_up` succeeded,
otherwise returns the single page as-is (`[words]`). Everything downstream
just iterates over "logical pages" without caring whether a split happened.

---

## 6. Stage 3 — Locator

**File:** `finagent/locator.py` · **Job:** out of hundreds of pages, find the
three we care about — the **Balance Sheet**, the **Profit & Loss**, and the
**Cash Flow** statement — and prefer the *consolidated* (group-wide) version
over the standalone one. This is pure keyword/number scoring over the text the
profiler already extracted.

### `NUM_RE`
A regex that recognises a "money figure." It matches two shapes:
- a long comma-grouped integer like `1,58,788`, **or**
- a decimal with two places like `8207.65`.

The decimal shape is essential: reports printed in crores have small 4-digit
decimal line items that the comma pattern alone would miss (BHEL's whole P&L
scored zero without it). We count these to tell a real statement page (many
numbers) from a table-of-contents mention (few numbers).

### `STATEMENT_SIGNATURES`
The heart of the locator: for each statement (BS/PL/CF) a pair of pattern
lists — **(title patterns, content-cue patterns)**.
- **Title patterns** = how the statement is *named* ("balance sheet",
  "statement of profit and loss", "income statement" …). These include
  international wording too: IFRS reports say "profit **or** loss", banks say
  "capital and liabilities."
- **Cue patterns** = line items that *belong* on that statement ("total
  assets", "operating activities" …). Cues confirm we're on the real
  statement, not just a page that mentions its name.

### `class Location`
The result for one statement: which `statement` (BS/PL/CF), the `basis`
(consolidated / standalone / unknown), the `page_indices` it was found on
(0-based, best first), and the numeric `score`.

### `_loc_search(pat, text)`  (named `_search` in the package)
A search helper with a **kerning fallback**. PDF text layers sometimes split a
word internally — "BALANCE" comes out as "BAL ANCE". So if the normal search
fails, it retries with all spaces removed from *both* the pattern and the
text. Catches titles that look broken to a naive search.

### `_is_heading(line, title_pats)`
Answers: *is this line an actual statement heading, or just a sentence that
mentions the statement?* A heading has the title phrase at the **start** of
the line (after at most a 2-word prefix like "Consolidated" or a company
name). A prose sentence buries the phrase in the middle ("Provisions are
reviewed at each balance sheet date…"). Position is the discriminator. This
stops a notes paragraph from masquerading as the real statement.

### `_score_page(text, title_pats, cue_pats)`
Scores **one page** for **one statement type**. Returns `(score, basis,
is_heading)`. The logic, step by step:
1. Count title hits (each worth 3) and cue hits (each worth 1).
2. **Reject early** if there's no title, or fewer than 2 cues → score 0.
3. **Reject** if fewer than 8 money-figures → it's a table-of-contents
   mention, not the statement.
4. Look at the first 6 non-empty lines for a real *heading* (using
   `_is_heading`). Ignore "Condensed/Summarised/Abridged" headings — those are
   management-report summaries, not the statement itself.
5. **Reject** pages that parade too many distinct years (a 10-year overview
   table, not a 2-period statement). Heading-titled pages get more slack
   because footnotes legitimately cite years.
6. If a real heading was found, add a +5 bonus.
7. Work out the **basis**: prefer what the *heading line* says ("Consolidated
   Balance Sheet"); fall back to anywhere on the page mentioning
   "consolidated"/"standalone."
8. Final score = title points + cue points + a small bonus for how many
   numbers are on the page (capped).

### `locate(doc_profile)`  ← entry point
Ties it together. For each statement type:
1. Score every non-empty page with `_score_page`; keep the ones scoring > 0.
2. If nothing scored, return an empty `Location`.
3. **Prefer real headings:** if any candidate is heading-titled, only consider
   those (a notes page that merely says "consolidated" can't hijack the pick).
4. **Prefer consolidated** pages within that tier.
5. Sort by score (highest first); ties go to the **earlier** page (the
   statement itself comes before the notes that echo its words).
6. Take the best page, then check its immediate neighbours: if a statement
   spills onto the next/previous page, include it (via `_is_continuation`).
   Only *adjacent* pages — a distant page that also scores is a *different*
   copy (standalone, prior year) and mixing it would corrupt the numbers.

Returns `{BS: Location, PL: Location, CF: Location}`.

### `_is_continuation(text, cue_pats)`
A light test for "is this neighbouring page a continuation of the statement?"
— at least 1 cue and at least 8 numbers. Lower bar than a full match because
the page already sits next to a confirmed statement.

---

## 7. Stage 4 — Extractor

**File:** `finagent/extractors/geometric.py` · **Job:** turn the chosen pages
into raw rows of "label + numbers." Called **geometric** because financial
tables are usually **borderless** — there are no lines to detect. Instead we
take every word's x/y coordinates (from `pdfplumber`), rebuild the visual
rows, and split each row into a text label and its trailing numbers.

### The constants
- `NUM_CHARS` — the characters a number token may contain (`0-9 , ( ) . % -`
  and the various unicode minuses).
- `MINUS_TOKENS` — unicode minuses (`−`, `–`, `—`). European reports print a
  negative as a **detached** minus: "− 112,858" is two separate words.
- `MAX_SIGN_GAP = 4.0` — how close a detached minus must be to its number to
  count as a sign (vs a lone "−" that just means "nil").
- `PLACEHOLDER_TOKENS` — dashes that mean "nil/zero" in a value column.

### `class RawItem`
One extracted row: the `label` text, the list of raw number-strings
(`values`), the `page` it's on, the `source` ("geometric"), and `side`
(current / non-current — which balance-sheet section it sat under).

### `_is_numeric_token(tok)`
True if a token is a number-like string: it has at least one digit and every
character is in `NUM_CHARS`. Used to tell labels from values.

### `_merge_detached_minus(line)`
Walks a row left to right and **glues a detached minus onto the number it
signs**, but only if they're close enough (`MAX_SIGN_GAP`). A far-away "−" is
left alone because it's a nil placeholder, not a sign. So "− 112,858"
(adjacent) becomes "-112858", but a lone "−" in its own column stays a
separate nil token.

### `_lines_from_words(words, y_tol=2.5)`
Groups loose words back into **visual lines** by their vertical position
(`top`). Words within 2.5 points of each other vertically are the same row.
Returns a list of rows, each a list of words.

### `_items_from_words(words, page_index)`
The most intricate function in the project. It turns one page's words into a
list of `RawItem`s, while tracking context that single rows don't carry. What
it tracks as it scans rows top-to-bottom:
- **`section`** — the current heading text (e.g. "ASSETS", "I. INCOME").
- **`side`** — current vs non-current (the balance sheet repeats labels like
  "Trade receivables" under both; we must know which one we're on).
- **`pending`** — a candidate subtotal row that had numbers but *no label*
  (some reports print a section total as a bare number). It's only accepted as
  the subtotal if no normal labelled row follows before the section ends —
  because a subtotal is always the **last** row of its block.
- **`prev_text`** — the previous text-only line, so a wrapped label can be
  rejoined ("Profit for the year, representing total" + "comprehensive
  income… 419,056").

For each row it:
1. Merges detached minuses, then finds the boundary between the label (left)
   and the trailing numbers (right).
2. Fixes a split parenthesis: "...(refer note" | "15)" — the "15)" looks
   numeric and would wrongly become the value, so it's rejoined to the label.
3. **If the row has a label and numbers** → it's a real line item. It rejoins
   wrapped labels, qualifies bare "Total"/"Basic" rows with their section name
   (banks label a section total just "Total"), flushes any pending subtotal
   when a total/net row closes the block, and appends a `RawItem`.
4. **If the row has numbers but no label** (inside a current/non-current
   block) → stash it as a `pending` candidate subtotal.
5. **If the row is text only** → it's a heading: flush any pending subtotal,
   remember it as `prev_text`, set the `section`, and update `side` if the
   heading says "current"/"non-current" (note: "non-current" contains
   "current", so it's tested first).

Every wrong guess here degrades safely: a misattributed row simply fails the
fuzzy match later (becomes MISSING) rather than producing a wrong value.

### `_matches_statement(words, cue_pats)`
On a two-up sheet that got split, this decides **which half** belongs to the
statement we were sent for. Threshold is just **1 cue** (not 2) because the
locator already vouched for the page — here we only need to drop the *other*
statement sharing the sheet. A statement can legitimately span both halves.

### `extract(pdf_path, page_indices, cue_pats=None)`  ← entry point
The public extractor. For each requested page:
1. Open it with `pdfplumber` and pull the words.
2. Drop **rotated words** (vertical "Financial Statements" tabs in the margin
   that share a row-band with the table and corrupt the scan) — *unless* the
   whole page is rotated (a landscape page), where the filter stands down.
3. Run `logical_pages` (Stage 2) to split a two-up sheet.
4. If split and we have cues, keep only the half that matches the statement.
5. Run `_items_from_words` on each logical group and collect all `RawItem`s.

Returns the full list of raw rows. **It does not parse the numbers** — that's
the normalizer's job. Output stays deliberately raw.

---

## 8. Stage 5 — Normalizer

**File:** `finagent/normalizer.py` · **Job:** turn messy raw rows into clean,
*named* numbers. Three sub-jobs: parse number strings, drop reference columns
that aren't values, and fuzzy-match each label to our standard vocabulary.

### `MATCH_THRESHOLD = 88`
A label must score at least 88/100 similarity against a known synonym to
count as a match. High enough to avoid false matches, loose enough to absorb
wording differences.

### `class Extraction`
One understood metric: which `metric` it is, the clean `value`, the
`raw_label` it came from, the `page`, the `source`, the match `score`, and any
`extra_values` (usually the prior-year column).

### `parse_number(tok)`
Turns a number-string into a float, handling real-world messiness:
- strips trailing footnote marks (`* # †`),
- normalises unicode minuses to ASCII,
- treats `(1,234.5)` (accounting parentheses) as **negative**,
- removes commas and `%`,
- returns `None` for non-numbers like a bare "-" (nil).

So `(1,234.5)` → `-1234.5`, `1,49,982` → `149982.0`, `-` → `None`.

### `_looks_like_note_ref(tok, rest, label="")`
Detects a **note-reference column** that should be skipped. Reports often
print a small note number before the value: "Revenue … **24** … 1,49,982" —
the 24 is a footnote pointer, not the value. Rules:
- If the note ref was already glued into the label ("Inventories 10(e)"), the
  first number *is* the value → not a note ref.
- A bare 1–2 digit integer → note ref.
- A 3-digit bare integer → note ref **only if** the next number is ~100× bigger
  (the jump a real label→note→value row shows). This protects real 3-digit
  values like an fx effect of 718.
- A small decimal (e.g. "5.5") → note ref only if the next value is orders of
  magnitude larger (protects a real EPS of 8.05).

### `_looks_like_page_ref(tok, nxt)`
Detects a **second** reference column. Some statements (BHEL) print *both* a
Note column **and** a Page-cross-reference column before the values:
"Inventories | 10 | 289 | 9,869.49." After the note (10) is stripped, 289 is
the page where the note lives — not a value. This fires only after a note ref
was already removed (the double-column signature), the token is a bare 1–3
digit integer, and a real money figure (with comma/decimal) follows it.

### `_QUALIFIER` + `clean_label(label)`
`clean_label` normalises a label so it can be compared to synonyms. It
lowercases, then strips **meaningless qualifiers** defined in `_QUALIFIER` —
things like "/(loss)", "(used in)", "(in rupees)", "(note 24)", leading
numbering ("1.", "(iv)"), and a leading basis word ("Consolidated …"). It
deliberately **keeps** classification qualifiers like "(current)" /
"(non-current)" because those carry real identity — stripping them once caused
the non-current line to shadow the real value. So "Net profit/(loss) for the
year" cleans to "net profit for the year."

### `_cleaned_synonyms()` + `CLEANED_SYNONYMS`
Pre-cleans every synonym in the schema once at import time (running each
through `clean_label`), so matching compares apples to apples. Cached in
`CLEANED_SYNONYMS` so it's computed only once.

### `match_label(label)`
The fuzzy matcher. Cleans the label, then compares it to every cleaned synonym
using `rapidfuzz`'s `token_sort_ratio` (order-independent similarity). Returns
the best `(metric, score)` if it clears the 88 threshold, with two guards:
- An **"Other …"** line is a residual, not the total it resembles — "Other
  current liabilities" must not satisfy `current_liabilities`.
- A **directional** mismatch is rejected: "net profit **after** minority
  interest" vs "… **before** minority interest" scores 92 but means a
  different number, so a before/after swap is vetoed.

### `_label_matches(label)`
Returns *all* metric readings of a label. Normally that's one. But an
**appositive** label — "Profit for the year, representing total comprehensive
income for the year" (Newgen) — names the *same number twice*. It splits on
"representing" and matches both parts, so one row can satisfy two metrics.

### `normalize(raw_items, allowed_metrics=None)`  ← entry point
The orchestrator. For every raw row:
1. Get its metric reading(s) via `_label_matches`.
2. Skip metrics not allowed on this statement (passed in by the pipeline) —
   this stops a P&L label from matching a balance-sheet metric.
3. Enforce the **side** rule: a current-side metric won't take a row stamped
   non-current.
4. Strip a note-reference column, then a page-reference column, if present.
5. Parse the remaining tokens into numbers; the **first** surviving number is
   the value (leftmost = current year), the rest are kept as extras.
6. Keep the **best-scoring** extraction per metric (if two rows match the same
   metric, the higher similarity wins).

Returns `{metric: Extraction}` — the clean, named numbers.

---

## 9. Stage 6 — Validator

**File:** `finagent/validator.py` · **Job:** the paranoid clerk. Prove each
number with accounting identities and cross-statement ties. **No ground truth
needed** — the statements check themselves.

### `class Status`
The five possible verdicts: `VERIFIED` (passed a maths check), `PROBABLE`
(extracted, nothing confirms or contradicts it), `FLAGGED` (failed a check —
needs a human), `MISSING` (expected but not found), `DERIVED` (computed later
by the deriver, never by extraction).

### `IDENTITY_CHECKS`
The accounting rules, as data. Each is `(name, left-side metrics, right-side
metrics, optional metrics)` meaning **sum(left) == sum(right)**. Examples:
- balance-sheet identity: `total_assets == total_liabilities + total_equity`
- assets composition: `total_assets == current + non_current`
- profit build-up: `profit_before_tax == net_profit + tax_expense`
- cash-flow total: `net_change == operations + investing + financing` (+ an
  *optional* fx effect that only some companies report).

### `SIGN_AMBIGUOUS = {"tax_expense"}`
Tax is printed as a positive in Indian reports but as a negative line in
EU/IFRS layouts. So the identities must hold under *either* sign — this set
tells the maths to try both.

### `CROSS_STATEMENT_CHECKS`
The same number must appear on two different statements. Here: the closing cash
in the cash-flow statement must equal cash-and-equivalents on the balance
sheet. A powerful independent check because the two numbers are read from
different pages.

### `within_tolerance(a, b, ...)`
Rounding-aware equality. Reports round each line to the printed unit, so a sum
of rounded items can differ from the printed total by a unit or two. This
allows a small relative (0.5%) or absolute (2 units) difference so honest
rounding doesn't get FLAGGED.

### `class MetricVerdict`
The verdict for one metric: its `status`, `value`, `sources`, `page`, and the
lists of `checks_passed` / `checks_failed` (the receipts).

### `class Validator`
Collects proposed values and runs the proofs.
- **`add(metric, value, ...)`** — record a proposed value for a metric (there
  can be more than one if multiple extractors weigh in).
- **`_consensus(metric)`** — the **median** of all proposals for a metric, so
  one wild reading can't drag the answer.
- **`validate()`** — the main event. Steps:
  1. Compute the consensus value for every metric.
  2. **Cross-extractor voting:** if several extractors proposed a metric and
     they agree → pass; disagree → flag.
  3. **Run every identity check.** Build the left and right sums (skipping
     checks where a needed metric is missing). For the cash-flow check, the
     optional fx effect may sit *inside* the sum (BMW) or *outside* it (Airtel)
     — so it tries the with-fx reading first, then without, and passes if
     either ties. Passing members get the check in `checks_passed`; a failing
     check stamps all involved metrics with `checks_failed`.
  4. **Run cross-statement ties** the same way.
  5. **Assign a status per metric:** FLAGGED if any check failed, else VERIFIED
     if any check passed, else PROBABLE. Pick the value closest to consensus
     and record its page.
  6. Any expected metric never seen becomes MISSING.
  Returns a `ValidationReport`.

### `class ValidationReport`
Holds all verdicts plus helpers:
- **`by_status(status)`** — all verdicts with a given status.
- **`print_summary()`** — the console scoreboard with `[OK] / [?] / [!!] /
  [--] / [=>]` icons and the final counts.
- **`to_dict()`** — flattens everything for the Excel writer.

---

## 10. Stage 6b — Deriver

**File:** `finagent/deriver.py` · **Job:** fill in numbers the report **never
printed** but the trusted identities pin down exactly. Example: Airtel's
balance sheet prints no subtotal rows; BMW prints no `total_liabilities`. If
we already trust the other terms, algebra gives the missing one.

Crucial rule: derivation runs **after** validation and is marked `DERIVED`,
**never VERIFIED** — because a derived value satisfies its own identity by
construction, so re-checking it would be circular.

### `DERIVATIONS`
A list of `(target_metric, formula)` where a formula is a list of
`(input_metric, sign)`. Several formulas can target the same metric (e.g.
`total_liabilities` from equity-and-liabilities, *or* from assets). They
compete; the safest wins.

### `_TRUSTED = {VERIFIED, PROBABLE}`
Only VERIFIED or PROBABLE inputs may feed a derivation. A FLAGGED input already
failed a check; building on it would spread the error.

### `_expr(formula, inputs)`
Builds a human-readable string of the formula used (e.g.
`total_assets[V] - total_equity[V]`), recorded as the receipt for the derived
value. The letter in brackets is the input's status initial.

### `derive(report)`  ← entry point
For each metric that is currently MISSING:
1. Gather every formula that targets it whose inputs are all present and
   trusted.
2. Among those, pick the one resting on the **fewest unproven** inputs (prefer
   formulas built on VERIFIED terms); code order only breaks ties.
3. Compute the value. If it comes out **zero or negative** (these are all
   should-be-positive metrics), that signals an upstream extraction is corrupt
   — leave it MISSING but log the diagnostic rather than emit a bad number.
4. Otherwise replace the MISSING verdict with a `DERIVED` one carrying the
   value and its formula receipt.

No chaining: derived values are never used as inputs to other derivations
(single pass), so errors can't cascade.

---

## 11. Stage 7 — Writer

**File:** `finagent/writer.py` · **Job:** save the result as an Excel where
every value carries its receipt, colour-coded by trust level.

### `_clean(value)`
PDF text layers occasionally carry stray control bytes inside a label, and
`openpyxl` refuses to write those (it would crash the whole file). This strips
the illegal characters from strings; non-strings pass through untouched.

### `STATUS_FILL` / `STATEMENT_NAMES` / `HEADERS`
Lookup tables: the cell background colour per status (green/yellow/red/grey/
blue), the friendly statement names ("PL" → "Profit & Loss"), and the column
headers.

### `write_excel(report_dict, out_path, extractions=None, meta=None)`  ← entry point
Builds the workbook:
1. Optionally writes a bold title row (the source filename + timestamp).
2. Writes the header row in bold.
3. For **every** metric in the schema (so even MISSING ones show up), writes a
   row: statement, metric name, value, status, **page (converted to 1-based
   for humans)**, the exact label it matched, the sources, and the
   passed/failed checks. The status cell gets its colour.
4. Sets sensible column widths and freezes the header row so it stays visible
   while scrolling.

Saves the file and returns its path.

---

## 12. The Schema

**File:** `finagent/schema.py` · **Job:** the single vocabulary every stage
speaks. There's no logic here — it's the dictionary that makes the locator,
normalizer, validator, and writer agree on what a "metric" is.

### `METRICS`
A dictionary: `canonical_metric_name → {statement, synonyms, ...}`. For each of
the ~28 metrics it records:
- **`statement`** — which statement it lives on (PL/BS/CF), so the normalizer
  only matches it against the right pages.
- **`synonyms`** — the many ways companies word that line ("Turnover", "Net
  sales", "Revenue from operations" all → `revenue`). Matched fuzzily, so the
  list just needs to be representative, not exhaustive.
- **`side`** (some BS metrics) — "current", because labels like "Trade
  receivables" appear under both balance-sheet sections.
- **`optional`** (e.g. `fx_effect_on_cash`) — only multinationals report it; it
  feeds an identity but is never counted as MISSING.

### `ALL_METRICS` / `EXPECTED_METRICS`
- `ALL_METRICS` — every metric name.
- `EXPECTED_METRICS` — every *non-optional* metric. These are what the
  validator expects to find; anything here that's missing is reported MISSING.

### `metrics_for_statement(code)`
Returns the metric names that belong to one statement (PL/BS/CF). The pipeline
uses this as the `allowed_metrics` filter so a label on the P&L page can only
match a P&L metric.

---

## 13. The Pipeline

**File:** `finagent/pipeline.py` · **Job:** the conductor. It calls the seven
stages in order and passes each one's output to the next. This is the file to
read to see the whole story in 40 lines.

### `run(pdf_path, out_path=None, verbose=True)`  ← the entry point of the whole app
1. **Profile** the PDF (`profile`) and log a summary.
2. **Locate** the statement pages (`locate`) and log where each was found.
3. Create a `Validator` seeded with the expected metrics.
4. For **each statement** (BS, PL, CF) that was located:
   - **Extract** its pages into raw rows (`extract`), passing the statement's
     cues so two-up halves get picked correctly.
   - **Normalize** those rows into named metrics (`normalize`), restricted to
     the metrics allowed on that statement.
   - Feed every extraction into the validator.
   Doing this **statement by statement** is deliberate: it guarantees a label
   can only match a metric that belongs on the page it came from.
5. **Validate** (`v.validate()`) → then **derive** (`derive`) the gaps. Order
   matters: derive runs *after* validate so derived values never feed the
   proofs.
6. Print the summary (if verbose).
7. **Write** the Excel (`write_excel`), defaulting the output path to
   `output/<Company>_metrics.xlsx`.
8. Return the report.

The `if __name__ == "__main__"` block lets you run it from the command line:
`python -m finagent.pipeline <pdf>`.

---

## 14. Frequently asked "why"

**Why not just use a table-extraction library?**
Financial statements are usually borderless, so table detectors find nothing.
And even a perfect table read still can't tell you whether the numbers are
*right*. The value here is the verification layer, not the reading.

**Why median instead of average for consensus?**
One garbage reading (say, a note number mistaken for a value) would yank an
average far off. The median ignores a single outlier.

**Why is a DERIVED value not VERIFIED?**
A derived value is *computed from* an identity, so of course it satisfies that
identity — checking it against the same rule proves nothing. Marking it DERIVED
is honest about where it came from.

**Why does every wrong guess "degrade safely"?**
The design preference throughout: when unsure, produce **MISSING** (a visible
gap) or **FLAGGED** (a visible warning), never a confident wrong number. A
human can fill a gap; a human can't catch a lie that looks right.

**Why keep the test set so weird (banks, A3 sheets, EUR, foreign reports)?**
Each one breaks a different naive assumption. If the tool survives all of them,
it generalises to reports it has never seen — which is the whole point.

**Where do I start if I want to change something?**
- New metric or new wording → `schema.py`.
- A number is read wrong → `extractors/geometric.py` (reading) or
  `normalizer.py` (parsing/matching).
- A correct number is wrongly FLAGGED → `validator.py` (the checks/tolerance).
- A statement isn't found → `locator.py` (signatures/scoring).
Then run `benchmark.py` to confirm you improved the score without breaking
anything else.
