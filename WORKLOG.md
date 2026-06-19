# Work Log — Financial PDF Extraction Agent (v2)

Running track record: what we tried, what worked, what failed, what's next.
Newest entries at the top. Benchmark = `benchmark.py` over the 8 test PDFs
(28 metrics each; VERIFIED / PROBABLE / FLAGGED / MISSING).

---

# CI/CD learning track (separate from extraction)

Using this repo as a hands-on CI/CD practice ground now that extraction is
saturated. Numbered as "levels". Newest at top.

## 2026-06-19 — Level 6.4: publish to REAL PyPI (DONE)

Goal: ship the package to the public PyPI so anyone can `pip install` it.
Shipped in PRs #8 and #9. `akshu-finagent 0.2.0` is LIVE on pypi.org.

Restructured `release.yml` into **build once, publish many**: one `build` job
builds the wheel + sdist and uploads them as an artifact; separate jobs
download that same artifact and publish to PyPI and a GitHub Release. Each
publish job carries its own `environment` (`pypi`) and only the permission it
needs (`id-token` or `contents`) — per-job least privilege. Bumped 0.1.1 ->
0.2.0 (fresh version on a new project name).

**Gotcha 1 — PyPI name guard:** `pypi.org/pypi/finagent/json` returned 404
(name unclaimed), but registering it was rejected: "too similar to an existing
project." PyPI has a typosquat guard ON TOP of the exact-name check — a 404
does NOT mean the name is allowed. Renamed the DISTRIBUTION to `akshu-finagent`
(one line: `[project].name`); the IMPORT name stays `finagent` (PyPI name and
import name may differ). Knock-on: trusted publishers are per-project-name, so
the rename required re-registering pending publishers under the new name.

**Gotcha 2 — trusted-publisher claim collision:** tried to keep TestPyPI +
PyPI both. PyPI succeeded; TestPyPI failed with `400 Non-user identities
cannot create new projects`. The OLD `finagent` TestPyPI project (from 6.3)
had a trusted publisher with IDENTICAL OIDC claims
(owner/repo/`release.yml`/`testpypi`), so the token matched it and refused to
create `akshu-finagent` through it. Two publishers with identical claims
collide. Dropped the TestPyPI job (PR #9) — the sandbox had served its purpose.

**Next:** an environment approval gate; bump action versions to clear the
Node 20 deprecation warning.

## 2026-06-17 — Level 5: matrix + caching + the gate-rename gotcha

Goal: prove the code works on more than one Python version, and speed CI up.
Done through the proper branch -> PR -> merge flow learned in Level 4.
Shipped in PR #2.

Three changes to `.github/workflows/ci.yml`:
1. **Matrix** (`strategy.matrix.python-version: ["3.11","3.12","3.13"]`) — the
   test job runs three times in parallel, one per version.
   `fail-fast: false` so if one version breaks, the others still run and you
   see every failure at once.
2. **pip caching** (`cache: pip` on setup-python) — first run saves the
   downloaded packages, later runs reuse them. Free speed-up.
3. **`all-green` gate job** — the fix for the gotcha below.

**The gotcha (the real lesson):** adding a matrix RENAMES the status checks
from `test` to `test (3.11)`, `test (3.12)`, `test (3.13)`. The branch-
protection rule from Level 4 required a check literally named `test`, which
no longer exists — so it would block every PR forever. Fix: the `all-green`
job (`if: always()`, `needs: [test]`) passes only if all matrix jobs passed,
and we require THAT single check in branch protection. Now Python versions
can change anytime without touching the protection rule.

(PR #1 earlier added `.gitattributes` to normalise line endings.)

## 2026-06-17 — Level 4: branch protection = make CI a real gate

Goal: broken code physically cannot reach `main`. Before this, CI showed
red/green but nothing stopped a red merge.

- Set the branch-protection rule on `main` via `gh api` (command line, not
  the website) — defining infra as commands is itself a core CI/CD skill:
  reproducible and reviewable.
- Rule does two things: (1) no pushing straight to `main` — changes go
  through a Pull Request; (2) a PR can't merge unless the required status
  check is green. Required check at this point was named `test` (later
  swapped to `all-green` in Level 5).

## 2026-06-19 — Level 6.3: publish to TestPyPI (OIDC trusted publishing) — DONE

Goal: publish to a real package index so the package is `pip install`-able from
anywhere, using OIDC Trusted Publishing (no stored API token). Shipped the
workflow change in PR #5. First publish was BLOCKED on a registration mismatch;
fixed it and `finagent 0.1.1` is now live on TestPyPI (full `Release` run green:
build + Publish to TestPyPI + Publish GitHub Release, run 27831682393).

Changes to `release.yml`:
- `permissions: id-token: write` — lets GitHub mint the short-lived OIDC token
  the index verifies. No secret stored anywhere.
- `environment: testpypi` — must match the trusted-publisher registration.
- `pypa/gh-action-pypi-publish@release/v1` step with
  `repository-url: https://test.pypi.org/legacy/` (TestPyPI sandbox first).
- Bumped version 0.1.0 -> 0.1.1 (an index version is immutable; can't reuse one).

**The gotcha (the real lesson):** the first publish failed with
`invalid-publisher: valid token, but no corresponding publisher`. The OIDC
token minted fine and the request DID reach TestPyPI (confirmed in the log:
`repository-url: https://test.pypi.org/legacy/`). The cause was on the website,
not in code: PyPI matches the token's CLAIMS against the registered publisher
field-by-field, and one field didn't match. The claims GitHub sent were:
owner `Akshu24Tech`, repo `financial-pdf-extraction-agent`, workflow file
`release.yml`, environment `testpypi`. The mismatch was PyPI's "Workflow name"
field — it wants the FILENAME (`release.yml`), not the `name:` inside the file
(`Release`). **Fix:** corrected the trusted-publisher registration on
test.pypi.org, then `gh run rerun 27831682393 --failed` (tag v0.1.1 already
existed; no new tag needed) — went green on the retry. Key takeaways: a failed
publish does NOT consume the version, so 0.1.1 was reusable; and `invalid-publisher`
is always a registration/claims mismatch, never a code bug.

**Next:** real PyPI (drop `repository-url`, register a publisher on pypi.org);
optionally an environment approval gate; bump action versions to clear the
Node 20 deprecation warning.

## 2026-06-19 — Level 6.2: tag-triggered Release workflow (DONE)

Goal: the actual "CD" half — push a version tag, get a published release with
artifacts attached, hands-off. Shipped in PR #4.

New `.github/workflows/release.yml` (separate from ci.yml: different trigger,
different purpose):
- `on: push: tags: ['v*']` — fires ONLY on a version tag, never on commits.
- `permissions: contents: write` — least privilege; a release WRITES (creates
  the Release object), unlike CI which only reads.
- Builds wheel + sdist (`python -m build`), then `softprops/action-gh-release@v2`
  attaches `dist/*` and auto-generates notes from merged PRs.
- One build, no matrix: the wheel is `py3-none-any` (version-independent);
  matrix was for TESTING, which already happened in CI.

**Proven:** pushed tag `v0.1.0` -> Release v0.1.0 appeared with the wheel + sdist
attached, downloadable. First end-to-end CD success.
**Noted:** run warned that the actions target the deprecated Node 20 runtime —
bump `@v4`/`@v5` action versions when upstream ships updates (action-version
maintenance is part of owning a pipeline). Also: checks run twice on PRs because
the workflow triggers on both `push` and `pull_request`.

## 2026-06-18/19 — Level 6.1: make the project pip-installable (DONE)

Goal: turn the folder of `.py` files into a buildable package so CD has
something to ship. Shipped in PR #3.

- Added `[build-system]` (setuptools backend) + `[project]` metadata
  (name, version, deps, `requires-python`) to `pyproject.toml`.
- Dependencies are listed in BOTH `requirements.txt` (dev setup) and
  `[project].dependencies` (baked into the wheel for installers) — different
  jobs, mirrored by hand.
- Gitignored `build/` and `dist/`.

**The gotcha (the real lesson):** first build "succeeded" but the wheel was
BROKEN — `packages = ["finagent"]` shipped only the top-level package and
silently DROPPED the `finagent.extractors` subpackage. A build can succeed and
still ship an un-importable package — always inspect what's inside the wheel.
Fix: auto-discovery via `[tool.setuptools.packages.find]` with
`include = ["finagent*"]` (also keeps tests/ and golden/ out). Verified
`finagent/extractors/` is in the rebuilt wheel; `twine check dist/*` PASSED.

---

## 2026-06-12 — **GOLDEN 180/180** (final-four round)

**Categories (3) + one golden correction:**
1. **Parenthesized enumeration prefixes** (`normalizer.py`): leading
   "(ii) " / "(a) " / "(12) " stripped (the old rule only handled "iv.").
   Adani's "(ii) Trade Receivables" rows — whose sides were already
   correctly stamped — now match; the side veto picks current 4,217.86
   over non-current 106.30.
2. **Total-row flush** (`extractors/geometric.py`): a pending unlabeled
   subtotal followed by a total-ish row ("TOTAL LIABILITIES", "NET CURRENT
   ASSETS") is FLUSHED, not discarded — totals follow subtotals, so the
   row before them is the real subtotal. Plain item rows still discard
   (wrapped-orphan protection). Closes both Wilmar liabilities subtotals
   (32,128,239 / 8,452,693) and VERIFIES whole composition groups
   (Wilmar 11→15V, Airtel 6→11V).
3. **Regulatory-deferral eps** (`schema.py`, `normalizer.py`): "(face
   value …)" parentheticals whitelisted; synonym "basic / diluted earnings
   per equity share after net movement" (as truncated by the line wrap —
   the regulatory tail wraps BELOW the values). The "before Net movement"
   twin (16.14) is vetoed by the before/after directional guard, exactly
   as designed.
4. **Golden correction #4**: Adani eps_basic 8.05 → 9.05. The recorded
   label didn't match the print; the visual render (Adani_p553.png) shows
   9.05, and PAT 921.69cr / ~101.8cr shares ≈ 9.05 confirms. Documented
   in golden.json with a note.

**Results:** golden **180/180 CORRECT, 0 WRONG, 0 MISSING, 0
VERIFIED-but-wrong** — every value the pipeline emits for every golden
slot in all 8 deliberately-different PDFs is externally correct.
Benchmark: **V 89→100**, P 70, F 12, D 10, M 36 (non-golden metrics the
statements genuinely don't print), zero per-file drops.

**Day summary (2026-06-11 → 12):** V 33→100, MISSING 113→36, golden
121→180 CORRECT, wrong values 11→0 — via ~25 named categories, zero
per-file special cases, full gates after every round, the golden gate
catching four regressions mid-flight and four reader misreads, and the
background roaster killing two real design errors (lateral-shift
parenthetical stripping; first-wins subtotal tiebreak) while its
measurable false alarms were dismissed with numbers.

## 2026-06-12 — Sweep round: golden 176/180, six files fully correct

**Trigger:** per-metric diagnostic sweep of all 14 remaining golden gaps
(each printed with golden value/page/label). 10 were synonym near-misses,
1 the known Newgen combined line, 3 structural (deferred).

**Categories (3):**
1. **Report-wording synonyms** (`schema.py`, 8 additions, each measured to
   ~98-100 before shipping): CF "net cash (flows) generated from
   investing/financing activities" (TCS/Adani/Wilmar); fx "exchange
   difference on translation of foreign currency cash and cash
   equivalents" (TCS); eps "earnings per equity share basic and diluted"
   (TCS combined line) + "basic earnings per ordinary share in eur" (BMW);
   net_profit "profit after tax for the year" (Adani); depreciation
   "depreciation amortisation and depletion expense" (Reliance);
   closing_cash "closing balance of cash and cash equivalents" (Reliance).
2. **Appositive labels** (`normalizer.py` `_label_matches`): a label
   containing " representing " names the same number twice — split and
   match each part, one row satisfying two metrics (Newgen "Profit for the
   year, representing total comprehensive income for the year").
3. **Wrapped-label join** (`extractors/geometric.py`): a numeric row whose
   label starts lowercase continues the immediately-preceding text-only
   line. Added mid-round when the golden gate caught the appositive split
   matching the SOCIE's echo of the wording (net_profit 495,530 prior-year
   instead of 419,056): the TRUE PL line was wrapped ("…representing
   total" + "comprehensive income … 419,056") and invisible. After the
   join it matches at 100 and wins the first-wins tie against the SOCIE.

**Results:** golden CORRECT 166→**176**, WRONG 0, MISSING 4, V-but-wrong 0.
Fully correct files: **TCS 27/27, Reliance 27/27, Airtel 26/26, BMW 22/22,
Newgen 14/14, HDFC 14/14**. Benchmark V 72→89 (Newgen net_profit VERIFIED
via profit buildup), F 12, M 41, zero per-file drops.

**Roast:** widest-blast-radius claim ("cash generated from operations" vs
new CF synonyms) measured dead at 59-65. Kept noted-later: synonym set
~110 with no second-best-score visibility or deletion process; eps header
row carrying a value on basic≠diluted filings; attributable-vs-total is
not covered by the before/after guard.

**Remaining 4 gaps (structural, diagnosed):** Adani eps (label matches at
88.9 but value path fails — note-ref/page issue) + trade_receivables
(current-side BS page p552 likely not in locator's page set); Wilmar
current/non-current liabilities subtotals (likely cross-page block:
side_heading does not survive page boundaries).

## 2026-06-12 — Airtel PL round: Airtel 26/26; golden 166/180, still 0 WRONG

**Categories (3):**
1. **Rotated margin text** (`extractors/geometric.py`): vertical page-tab
   words ("Financial Statements", pdfplumber upright=False) share a y-band
   with table rows and kill the numeric-tail scan (Airtel TCI line ended
   "... 400,507 (14,398) Statements" → no-value heading). Words with
   upright=False are dropped — UNLESS most of the page is rotated
   (landscape tables), where the filter stands down (roast catch).
2. **Unlabeled section subtotals** (`geometric.py`): Airtel's BS prints
   subtotal rows as bare number rows with NO label ("4,467,716 3,862,549").
   An unlabeled numeric row inside a current/non-current block becomes the
   PENDING subtotal; any labeled row after it discards it (a subtotal is
   the LAST row of its block — roast inverted my first-wins design and was
   right); a heading or page end flushes it as "total {side-heading}";
   a labeled "Total …" row closes the block. Safety: wrong synthesis fails
   fuzzy, loses the first-wins tie to a real row, or breaks a composition
   identity.
3. **tax derivation** (`deriver.py`): tax_expense = PBT − net_profit for
   P&Ls that print only Current/Deferred sub-lines (Airtel 9,172 ✓).
   EU-sign risk documented in code; positive-only guard.

**Results:** Airtel 20→**26/26** golden (second complete file after HDFC).
Spillovers, all golden-confirmed: Wilmar +2 (19/22), Reliance +1 (25/27),
Adani +1 (24/28) — the subtotal synthesis and tax derivation generalized.
Benchmark: V 72, P 77→82, D 8→14, M 61→50, zero per-file drops.
Golden TOTAL: **166 C / 0 W / 14 M / 0 V-but-wrong**.

**Diagnosis notes:** eps was a false lead (already extracted); the real
Airtel PL culprits were the rotated tab and the no-total tax section.
Golden's BS subtotal values exist in the text layer as pure number rows —
the labels were never in the text at all.

## 2026-06-12 — Basis-prefix round: HDFC golden 14/14 (first fully-correct file)

**Categories (3):**
1. **Basis-prefix strip** (`normalizer.py`): a LEADING "consolidated"/
   "standalone" on a label is page-level info the locator already resolved,
   not label identity — stripped in clean_label (interior occurrences
   untouched).
2. **Bank net-profit synonym** (`schema.py`): "net profit for the year
   before minority interest" (the before-MI line is the total incl. NCI —
   same convention as "profit for the year" elsewhere).
3. **Directional-qualifier guard** (`normalizer.py`): the roaster predicted
   and measurement confirmed "net profit for the year AFTER minority
   interest" scores 92.6 vs the new BEFORE synonym (one-token swap, same
   class as the tax/total 92). A match is vetoed when exactly one of
   label/synonym says "before"/"after". Verified: plain "Profit before tax"
   (both sides "before") unaffected; the owners-only "attributable to the
   group" line is at 59.8, never matched.

**Results:** HDFC net_profit 73,440.17 = exact golden → **HDFC golden
14/14, zero gaps, zero wrongs** — was the worst file (0V/24M) three days
of rounds ago. Benchmark: HDFC 10V/5P/14M; all 7 other files
byte-identical (TOTAL 72/77/9/8D/61). Golden: 157 C / 0 W / 23 M /
**0 V-but-wrong**.

**Roast noted-later:** banks that print ONLY the attributable line will
return net_profit=MISSING (correct behavior, but a coverage gap);
consolidated/standalone two-up sheets where the prefix disambiguated
same-page columns — no such layout in corpus; raw labels are already
stored next to cleaned matches in the xlsx (Matched label column), so
pre/post-strip diffing is possible.

## 2026-06-12 — Derivation stage (`finagent/deriver.py`): MISSING 70→62, still 0 WRONG

**Category: derivable metrics.** New stage 6b after validation: EXPECTED
metrics still MISSING are computed from accounting identities when every
input is VERIFIED/PROBABLE (never FLAGGED, never DERIVED — no chaining by
construction). Formulas: BS compositions (total_liabilities = EQ&L −
equity, current = total − non-current, both directions), the BS identity
itself (EQ&L = total_assets), total_income = revenue + other_income.
Deliberately excluded (comment in code): CF derivations (fx placement
ambiguity), total_expenses (exceptional/JV items), PBT (tax signs).

**Honesty mechanics (most from the roast):** new status **DERIVED** —
never VERIFIED, a derived value satisfies the deriving identity by
construction and the validator runs first (ordering documented in
pipeline.py). Competing formulas ranked by fewest non-VERIFIED inputs,
not code order. Provenance string in the xlsx: "derived:
total_equity_and_liabilities[V] - total_liabilities[P]". Non-positive
results logged on the MISSING verdict, not silently discarded. DERIVED
plumbed through print_summary icons, writer fill (blue), benchmark table
(new column — history rows before this entry have no D column).

**Results:** V/P/F byte-identical to the Airtel round (72/76/9) — the
stage cannot touch extractions; 8 DERIVED (BMW 2, Airtel 2, Adani, TCS,
Newgen, Wilmar 1 each); MISSING 70→62. Golden: CORRECT 153→156
(Airtel total_equity 1,534,677 — the NCI-definition risk case — and
total_income, Adani +1), **WRONG 0**, V-but-wrong 0. Every derived value
with golden coverage is externally correct.

**Roast noted-later:** golden coverage of derived slots is sparse (a wrong
derivation outside coverage ships silently); PROBABLE inputs propagate
unproven values — watch when corpus grows; the DERIVED column must not
become an optimization target (exclusion rationale is in the code).

## 2026-06-12 — Airtel round: golden WRONG = 0 for the first time

**Categories (6 — over the ≤3 budget; each was smoke-verified on its target
file before the next, which serves as the attribution record):**
1. **Two-up statement span** (`extractors/geometric.py`): half-picker
   threshold ≥2→≥1 cue — the locator already vouched for the page; the
   picker only needs to drop the OTHER statement on a shared A3 sheet.
   Airtel CF financing half (1 cue) was being discarded. Also fixed
   Reliance (+4V, 11→15) — same layout.
2. **Section-side veto** (`geometric.py`, `schema.py`, `normalizer.py`):
   RawItems stamped current/non-current from headings (non-current tested
   first!); side hints on trade_receivables/inventories/cash_and_equivalents
   = current. Airtel trade_receivables 2,131→74,557 (the last golden WRONG
   until this round). Veto failure mode is MISSING, never a wrong value.
3. **Letter-ref parentheticals** (`normalizer.py`): "(a)", "(a+b+c)" join
   the qualifier whitelist.
4. **Split parenthetical rejoin** (`geometric.py`): "… (refer note | 15)" —
   the closing fragment looked numeric and became the value (closing_cash
   would be 15!); unbalanced-paren labels reabsorb such tokens.
5. **fx placement ambiguity** (`validator.py`): optional identity members
   (fx) sit inside the sum (BMW) or outside in the opening→closing
   reconciliation (Airtel "(a+b+c)"); the identity passes if either
   reading ties; with-fx tried first so BMW's fx keeps VERIFIED credit.
6. **Note-ref magnitude refinement** (`normalizer.py`) — fixed the two
   regressions the golden gate caught mid-round (TCS inventories 28-vs-21
   back; Airtel fx −8,851 vs 718): (a) label ending in a note token
   ("Inventories 10(e)") means the note column is consumed — keep the first
   value; (b) bare ints ≤2 digits stay note refs (protects EPS rows);
   (c) 3-digit ints are note refs only when the next value is ≥100× larger.

**Results:** benchmark V 64→72 (Airtel 2→6, Reliance 11→15), M 76→70, no
per-file drop (Airtel F 0→2 = the by-design closing-cash↔BS-cash tie flag,
Newgen-style). Golden: CORRECT 145→153, **WRONG 2→0** (first all-correct
run), MISSING 27, V-but-wrong 0. Every extracted golden value in all 8 PDFs
is now externally correct.

**Roast notes (background agent):** side-state staleness across "Equity"
headings is a ticking clock if equity-side metrics ever get side hints;
the ≥1 half-picker's blast radius depends on locator false-positive rate
on notes/SOCIE sheets (one corpus data point); a misfiring veto shows as
a golden CORRECT drop, NOT a WRONG — watch that column. Noted-later.

## 2026-06-12 — Qualifier cleaning round (HDFC 10V; golden gate caught its first regression)

**Categories (3):**
1. **Sign/unit/reference qualifiers** (`normalizer.py`): labels and synonyms
   are cleaned through the same `clean_label()`, which strips slash-alternates
   ("/(loss)", "/loss" — BMW prints "Profit/loss before tax" with no parens)
   and a WHITELIST of parentheticals: (used in), (decrease), (in rupees),
   (rs.), (note …), (refer …), (net of …), (continued). Synonyms precomputed
   as `CLEANED_SYNONYMS` (101 distinct, zero cross-metric collisions).
2. **Bare sublabels basic/diluted** (`extractors/geometric.py`): the
   section-qualified rewrite now also covers "Basic"/"Diluted" rows under an
   "Earnings per equity share" heading; section headings are captured with
   parentheticals stripped (face-value/unit noise). eps_basic synonym
   "earnings per equity share basic" added (old best score was 87.3).
3. **fx vocabulary** (`schema.py`): "effect of fluctuation in foreign
   currency translation reserve" (HDFC wording) — turned HDFC's whole CF
   block VERIFIED (identity off by exactly the 199.73 fx effect before).

**The instructive failure:** the first version stripped ALL parentheticals.
The golden gate caught 3 new WRONGs (TCS inventories, Adani + Airtel
current/non-current shadowing: "(non-current)" stripped → both lines clean
identical → first occurrence wins → non-current section comes first in an
Indian BS) and BMW dropped 14V→11V (synonym "profit/(loss) before tax"
over-cleaned while BMW's parenless "Profit/loss before tax" under-cleaned —
PBT lost, profit-buildup identity broke). Exactly the roaster's predicted
"lateral shift" class. Whitelist corrections: classification parens
("(current)", "(non-current)") survive and block matches; bare "(net)" NOT
whitelisted ("Current tax liabilities (net)" scored 92 vs "total current
liabilities" — tax/total one-token swap clears 88!).

**Results (vs bare-section-totals baseline):** benchmark V 59→64, M 80→76,
zero per-file drops (BMW restored 14V; HDFC 10V/4P/15M — eps_basic 92.81 and
cash_from_investing −3,850.64 both exact golden). Golden: CORRECT 140→145,
WRONG 1 (pre-existing Airtel trade_receivables only), MISSING 39→34,
**V-but-wrong 0**.

**Scoped next (verified premises):**
- **Two-up statement span** (Airtel CF): p200 holds the WHOLE CF — left half
  ops+investing, right half financing+net change+closing. The half-picker
  needs ≥2 cues, financing half has 1 → discarded. Fix: keep every half
  with ≥1 cue once the page is located (allowed_metrics guards the rest).
- **Section-side veto** (Airtel trade_receivables): "Non-current assets" /
  "Current assets" headings verified present before the duplicate
  "- Trade receivables" rows; stamp RawItems with a current/non-current side
  and veto current-side metrics matched under non-current.
- Airtel BS prints NO subtotal rows (no "Total current liabilities" line
  at all) — its subtotal MISSINGs may be unfixable from this statement page.
- Airtel PL: "Tax expense / (credit)" renders as a no-number line (values
  land elsewhere) — investigate the PL half's line geometry.
- HDFC residue: net_profit long-label ("Consolidated Net Profit for the
  year before Minority Interest") still the deferred matching category.

## 2026-06-11 (evening) — Bare section totals (HDFC 0V → 5V)

**Category** (`extractors/geometric.py`, `schema.py`): bank/RBI statements
label total rows just "Total" under a section heading. The extractor now
remembers the most recent text-only line as the section candidate and
rewrites a bare "Total" label to "total {section}" ("ASSETS" →
"total assets", "I. INCOME" → "total income"); leading roman/decimal
numbering stripped from the section. Misattribution degrades to a fuzzy
non-match (absence), not garbage. Schema: total_equity_and_liabilities +=
"total capital and liabilities".

**Results:** HDFC 0V/7P/21M → **5V/6P/17M** (total_assets,
total_eq&liab, total_income all VERIFIED at exact golden values;
revenue + other_income promoted to VERIFIED by the income identity;
total_expenses PROBABLE at golden value). All 7 other files
byte-identical. TOTAL: V 54→59, M 84→80. Golden: HDFC CORRECT 6→10,
TOTAL 140 C / 1 W / 39 M, V-but-wrong 0.

**Roast (background) — kept/dismissed:**
- Kill shot was "wrapped-label fragments make plausible wrong sections":
  didn't materialize in-corpus (only HDFC changed); rewrite side-products
  "total profit"/"total appropriations" verified to match nothing
  (fuzzy 54-58). Noted-later: nested corporate layouts with bare totals
  need a heading *stack*; unbounded heading-to-total distance; column
  headers ("Particulars") burning the candidate slot.
- Out of scope, logged: Newgen-style subtotal rows with NO label at all.

**Next categories scoped from HDFC p441/442 line dump:**
- **Parenthetical sign-qualifiers**: "Net cash flow from / (used in)
  investing activities" scores <88; stripping non-note parens + "/" gives
  exact 100 (measured). Must clean synonyms identically ("basic (in
  rupees)") or existing matches regress.
- **Bare sublabels basic/diluted**: HDFC eps lines are "Basic 92.81" /
  "Diluted 92.39" under an "Earnings per equity share" heading — extend
  the section-rewrite whitelist; "earnings per equity share basic" vs
  existing synonym = 87.3 (just under 88), so add the exact synonym.
- net_profit "Consolidated Net Profit for the year before Minority
  Interest" = long-qualified-label category; needs a careful matching
  change (token_set is too dangerous), deferred.

## 2026-06-11 (evening) — Bank vocabulary round (HDFC BS located, revenue extracted)

**Categories (2, kept small per no-omnibus rule):**
1. **Bank BS locator cues** (`locator.py`): Banking Regulation Act Schedule III
   wording — "capital and liabilities", "reserves and surplus", deposits,
   advances, borrowings. HDFC consolidated BS now locates (p440 0-based,
   basis=consolidated from the heading); before: BS pages=[].
2. **Bank revenue synonym** (`schema.py`): `revenue` += "interest earned".
   Collision risk measured before shipping: token_sort_ratio("interest
   income", "interest earned") = 73, "interest expense" = 77 — both far
   below the 88 threshold. Roaster's predicted ≥88 collision was wrong.

**Results:** benchmark HDFC 6P→7P, M 22→21; all 7 other files
**byte-identical** — the generic cues (deposits/advances) mislocated
nothing in-corpus. Golden: HDFC CORRECT 5→6 (revenue 336,367.43 = golden
"Interest earned" exactly), TOTAL 136 C / 1 W / 43 M, V-but-wrong 0.
Bonus: finance_costs now picks up bank "Interest expended" (PROBABLE,
not golden-covered). The located BS page produced NO garbage — its
metrics stay honestly MISSING (all bare "Total" section lines).

**Roast (background) — kept/dismissed:**
- Dismissed by measurement: "interest earned"≈"interest income" collision
  (73 < 88); present-but-wrong BS extraction (didn't happen, verified
  per-metric).
- Kept (noted-for-later): cues are global — NBFC/other-bank PDFs outside
  the corpus could false-positive on deposits/advances notes pages; the
  ≥8-numbers threshold and corporate cue calibration untested on more
  banks; only 1 bank in corpus = anecdote, not validation.
- **Next HDFC category (deferred deliberately): bare section totals** —
  bank statements label totals just "Total" under a section heading
  (Total under ASSETS = total_assets; I. INCOME / II. EXPENDITURE on PL).
  Same category as Newgen's unlabeled subtotal rows. Unlocks HDFC
  total_assets, total_eq&liab, total_income, total_expenses.
- Also open on HDFC PL: net_profit label is "Consolidated Net Profit for
  the year before Minority Interest" (too long for fuzzy 88), eps/tax
  lines not matched; CF investing line missed.

## 2026-06-11 (evening) — Locator heading-tier round: golden WRONG 8→1

**Categories fixed** (`locator.py`, `normalizer.py`):
1. **Heading tier** — pages whose statement title is a true top-of-page
   heading form their own pool; notes pages that merely echo keywords can
   never outrank them. Fixes Airtel CF (notes p218 → real p200) and
   Wilmar BS (notes p107-109 → real p20-21).
2. **Earlier-page tiebreak** — the statement precedes the notes/SOCIE pages
   that echo it.
3. **Fragmented titles** — `_search()` retries patterns against
   space-collapsed text (kerning-split "BAL ANCE SHEET").
4. **Year-overview slack** for headed pages (threshold 10 vs 6) so footnotes
   citing many years (Airtel spectrum list) don't disqualify a statement.
5. **Decimal note-refs** — leading "5.5" dropped only when next value ≥100×
   larger (kills Adani depreciation 5.50; EPS pairs survive).
6. **"Other …" residual guard** — "Other current liabilities" can't satisfy
   `current_liabilities`.

**Results:** benchmark V 50→54, F 8→7, M 88→85 (P flat 79).
Golden: CORRECT 125→135, WRONG 8→1, MISSING 47→44, **V-but-wrong 0**.
Per-file: Wilmar 3V→7V (M 16→11) — both its golden WRONGs gone;
Adani bogus depreciation gone; Airtel golden WRONG 5→1.

**Airtel benchmark dip, examined (M 11→13):** the mislocated notes page
used to supply *wrong* CF values that counted as PROBABLE; with the real
CF page they're honestly MISSING. Checked: 12 of Airtel's 13 missing
metrics are golden-covered (only `total_expenses` is a blind spot), so the
dip is golden-supervised wrong→missing — an improvement. **Carve-out
criterion adopted (from roast):** a per-file benchmark drop is acceptable
ONLY when every regressed slot is golden-covered and golden grades the
file's net change as improved. A drop touching golden-uncovered slots is
a real regression, full stop.

**Roast findings (background plan-roaster) — adopted/open:**
- **HDFC claim was false**: kerning fix did NOT fix HDFC — BS still
  unlocated (pages=[]). Re-diagnosed by reading p440 text: title is clean
  ("CONSOLIDATED BALANCE SHEET", quality OK); the blocker is the **cue
  check** — bank BS vocabulary is "CAPITAL AND LIABILITIES", "Reserves and
  surplus", "Deposits", "Advances", no current/non-current split → cues<2 →
  score 0. New named category: **bank balance-sheet vocabulary** (cues +
  schema). HDFC PL (p441) and CF (p442-443) locate fine.
- Avoid omnibus rounds: 6 fixes landed together → no per-fix attribution.
  Prefer ≤2-3 categories per round, benchmark between.
- Kerning collapse is substring-y on collapsed text — false-positive
  surface unmeasured ("notes to the balance sheet" pages). Watch it.
- Remaining golden WRONG (1): Airtel `trade_receivables` 2,131 vs 74,557 —
  non-current trade-receivables line matched instead of current. Category:
  current/non-current section disambiguation on the BS.
- Airtel CF financing residue: CF located as [200] only;
  cash_from_financing / net_change_in_cash / closing_cash MISSING —
  financing section likely on the following page/half; continuation or
  two-up half-selection drops it.
- TCS now 197s (was ~170s). No perf gate exists; benchmark already prints
  per-file time — informal budget: no file should exceed 2× its round-1
  baseline.

## 2026-06-11 — Golden dataset built (`golden/golden.json` + `golden_check.py`)

**What:** hand-read ground truth for ~25 metrics/PDF across all 8 test files,
read from VISUAL page renders (pypdfium2 4-6×, `render_pages.py`, two-up pages
split into halves/quadrants) — independent of the text layer the extractor
parses. Every value identity-cross-checked at reading time; three of my own
misreads were caught and fixed this way (Reliance NCA, Airtel total assets,
Wilmar investing CF). A background plan-roaster agent attacked the design
first; adopted: visual-not-text provenance, per-value page/label/unit fields,
graded mismatches (CORRECT / SCALE / SIGN / WRONG / MISSING) instead of
binary, headline metric = VERIFIED-but-wrong. Documented limits: correlated
reader bias mitigated not eliminated; 8 PDFs ≠ generalization; stale when a
test PDF changes.

**Locator bugs found just by reading pages (open):**
1. **Airtel CF mislocated** — locator picks p218 (a NOTES page summarising
   subsidiaries' cash flows!) instead of the real consolidated CF on p201.
2. **Wilmar BS mislocated** — locator picks notes pages 107-109; real
   "BALANCE SHEETS" (Group + Company columns) is p20-21.
3. **HDFC BS invisible** — p441 title renders as "BAL ANCE SHEET" (kerning
   split inside the word); title regex can't see it. Category: fragmented
   titles → match against space-collapsed text too.
4. **Newgen ops-cash wrong line** — pipeline takes "Cash generated from
   operations" 843,346 (pre-tax) instead of "Net cash generated from
   operating activities" 698,072. Category: prefer the "net …" total over
   the pre-tax subtotal when both match.

**Units recorded per file (future unit-detection stage must produce these):**
TCS/Reliance/Adani/HDFC = INR crore; Airtel = INR million (!);
BMW = EUR million; Wilmar = USD thousand; Newgen = SGD units.

**First golden_check run (before any fix):** 180 golden values →
121 CORRECT / 1 SIGN / 11 WRONG / 47 MISSING, and **VERIFIED-but-wrong = 0**
(every validator-proven value is externally correct). The 11 WRONGs cluster:
- pre-tax "Cash generated from operations" subtotal taken as ops cash on
  Reliance (1,70,749 vs 1,58,788), Adani (8,923.92 vs 8,695.22), Newgen
  (843,346 vs 698,072) → fixed by REMOVING that synonym from schema (it is
  always the pre-tax subtotal, never the net total).
- Airtel (5) + Wilmar (2): the mislocated-statement bugs already logged.
- Adani depreciation 5.50: bogus line match on the BS page.
Newgen golden tax sign corrected to match print (-105,313, parens).

## 2026-06-11 — BMW deep-dive: 6 stacked category fixes (per-file: 2V/22M → 14V/0F/8M)

**Trigger:** BMW worst file (22 MISSING). Each fix below is a named category,
none is BMW-specific. Full-benchmark verdict pending (see history table).

1. **Multi-year overview filter** (`locator.py`): the PL was "found" on the
   ten-year comparison page (p427). Real statements show two comparative
   periods (IAS 1); a page with ≥6 distinct year tokens is an overview → score 0.
2. **Detached unicode minus** (`extractors/geometric.py`, `normalizer.py`):
   EU reports print "− 112,858" as two words; the trailing-number scan choked
   and grabbed the wrong column (revenue read 24,333 = Eliminations-2024
   instead of 133,453 = Group-2025!). Merge a unicode minus into the next
   number **only if it hugs it** (x-gap ≤ 4pt) — a distant "−" is a nil
   placeholder, not a sign.
3. **Heading boost + title-line basis** (`locator.py`): a real statement
   carries its title as the page heading; management-report prose merely
   mentions it. +5 score when a title pattern hits the top-6 lines. Basis
   (consolidated/standalone) is read from the title line itself — German
   "for Group and Segments" = consolidated; prose/breadcrumb "consolidated"
   no longer hijacks the preference pool (BMW AG standalone BS trap).
4. **Condensed-title demotion** (`locator.py`): "BMW Group Condensed Balance
   Sheet" (management report summary) — condensed/summarised/abridged titles
   get no heading boost and no basis authority.
5. **Nil placeholders are tail members** (`extractors/geometric.py`): rows
   ending "… 1 1 − −" lost ALL their values (scan stopped at the dash) —
   that's why Inventories/Cash/Intangibles vanished. Standalone dashes now
   belong to the numeric tail.
6. **Validator conventions** (`validator.py`, `schema.py`): (a) tax may be a
   negative line (EU) or positive charge (India) — net_profit_buildup holds
   under either sign; (b) new optional metric `fx_effect_on_cash` joins the
   cash-flow identity when present (never counted MISSING). BMW's whole CF
   then VERIFIED: 8,228 − 9,952 + 1,373 − 82 = −433 ✓.

Plus German/EU schema synonyms: "cash inflow/outflow from X activities",
"equity", "non-current provisions and liabilities", "income taxes",
"net profit/loss", "current assets", "cash and cash equivalents as at december".

**BMW residue (open):** total_liabilities not printed (derivable as
EQ&L − equity), eps/depreciation/employee costs labels, comprehensive income
on separate statement page.

## 2026-06-11 — IFRS locator vocabulary (DONE, proven)

**Trigger:** Newgen scored near-bottom (2 V / 20 M) despite being a "normal"
report, and ran suspiciously fast (2.2s).

**Diagnosis:**
- Newgen.pdf is NOT the Indian listed company — it's the Singapore subsidiary
  (Newgen Software Technologies PTE. LTD.), 43-page IFRS standalone accounts in S$.
- The P&L was never located: page titled "STATEMENT OF PROFIT **OR** LOSS AND
  OTHER COMPREHENSIVE INCOME" (IFRS wording); locator only knew the Indian
  "statement of profit **and** loss". One word → 0 title score → ~12 metrics missing.
- Content cues were India-only ("revenue from operations", "total expenses");
  IFRS says "gross profit", "cost of sales", "profit for the year".

**Fix (category: IFRS title/cue vocabulary, `finagent/locator.py`):**
added `profit (and|or) loss`, "statement of comprehensive income" titles;
added IFRS cues (gross profit, cost of sales, profit for the year, income tax expense).
No per-file code.

**Result:** Newgen 20→15 MISSING (revenue, PBT, tax, TCI now extracted);
HDFC 24→22 MISSING as a free side-effect (banks use IFRS-ish wording too);
all other 6 files unchanged. TOTAL: MISSING 113→106, PROBABLE 67→74.

**Known Newgen residue (different categories, open):**
- Singapore-style unlabeled subtotal rows (current_assets etc. have no label text)
- Combined line "Profit for the year, representing total comprehensive income"
  maps to one metric (TCI) instead of two (also net_profit)
- closing_cash (2,651,907) vs BS cash (4,012,907) correctly FLAGGED — CF closing
  cash excludes pledged deposits; real-world nuance, validator did its job.

## 2026-06-11 — Process rules (from /roast-my-plan on the improvement strategy)

User's fear: "fix one PDF → break another → stuck in a whack-a-mole loop."
Roast verdict and adopted rules:
1. **Category rule:** every fix must address a *named* failure category
   (e.g. "IFRS title wording"), never `if <company>` special cases.
2. **Benchmark gate:** full benchmark after every change; no file may drop.
3. **Open hole:** benchmark is self-referential — VERIFIED = internally
   consistent, NOT externally correct. A hand-checked **golden dataset**
   (~10 metrics/PDF vs the printed reports) is the highest-value missing
   artifact. Not built yet.

## 2026-06-11 — Stage 2 geometry fixer (DONE, proven)

`finagent/geometry.py`: conservative A3 two-up split — near-empty vertical
band closest to centre, real text on both sides, alpha-ratio check so a wide
table's number block isn't mistaken for a page. Wired into the geometric
extractor; cue patterns pick the matching half of a split page.
Result: Reliance (A3 two-up) became 2nd-best file (11 VERIFIED / 6 MISSING).

## Earlier — Stage 1 walking skeleton (DONE)

Full pipeline connected: profiler → locator → extractors/geometric →
normalizer → validator → writer. Benchmark harness over 8 deliberately
different PDFs. Venv rule: everything through `.venv\Scripts\python.exe`.

---

# Benchmark history

| Date | Change | V | P | F | M |
|---|---|---|---|---|---|
| 2026-06-11 | baseline (skeleton + geometry) | 33 | 67 | 11 | 113 |
| 2026-06-11 | IFRS locator vocabulary | 33 | 74 | 11 | 106 |
| 2026-06-11 | BMW round (6 category fixes) | 50 | 79 | 8 | 88 |
| 2026-06-11 | pre-tax ops-cash synonym removed | 50 | 79 | 8 | 88 |
| 2026-06-11 | locator heading-tier round (6 fixes) | 54 | 79 | 7 | 85 |
| 2026-06-11 | bank vocabulary (HDFC) | 54 | 80 | 7 | 84 |
| 2026-06-11 | bare section totals | 59 | 79 | 7 | 80 |
| 2026-06-12 | qualifier cleaning round | 64 | 79 | 7 | 76 |
| 2026-06-12 | Airtel round (span/side/fx/note-ref) | 72 | 76 | 9 | 70 |
| 2026-06-12 | derivation stage (D column: 8 derived) | 72 | 76 | 9 | 62 |
| 2026-06-12 | basis-prefix round (HDFC net_profit) | 72 | 77 | 9 | 61 |
| 2026-06-12 | Airtel PL round (rotated/subtotals/tax) | 72 | 82 | 9 | 50 |
| 2026-06-12 | sweep round (synonyms/appositive/wrap-join) | 89 | 72 | 12 | 41 |
| 2026-06-12 | final-four round (**golden 180/180**) | 100 | 70 | 12 | 36 |

# Golden-check history (180 golden values; headline = VERIFIED-but-wrong)

| Date | Change | CORRECT | SCALE | SIGN | WRONG | MISSING | V-but-wrong |
|---|---|---|---|---|---|---|---|
| 2026-06-11 | first run | 121 | 0 | 1 | 11 | 47 | **0** |
| 2026-06-11 | pre-tax ops-cash synonym removed | 125 | 0 | 0 | 8 | 47 | **0** |
| 2026-06-11 | locator heading-tier round (6 fixes) | 135 | 0 | 0 | 1 | 44 | **0** |
| 2026-06-11 | bank vocabulary (HDFC) | 136 | 0 | 0 | 1 | 43 | **0** |
| 2026-06-11 | bare section totals | 140 | 0 | 0 | 1 | 39 | **0** |
| 2026-06-12 | qualifier cleaning round | 145 | 0 | 0 | 1 | 34 | **0** |
| 2026-06-12 | Airtel round (span/side/fx/note-ref) | 153 | 0 | 0 | **0** | 27 | **0** |
| 2026-06-12 | derivation stage | 156 | 0 | 0 | **0** | 24 | **0** |
| 2026-06-12 | basis-prefix round | 157 | 0 | 0 | **0** | 23 | **0** |
| 2026-06-12 | Airtel PL round | 166 | 0 | 0 | **0** | 14 | **0** |
| 2026-06-12 | sweep round | 176 | 0 | 0 | **0** | 4 | **0** |
| 2026-06-12 | final-four round | **180** | 0 | 0 | **0** | **0** | **0** |

Remaining 8 WRONGs are all already-logged open bugs: Airtel ×5 (CF read from
notes p218 instead of p201; BS subtotal lines), Wilmar ×2 (BS read from notes
p106-109 instead of p20-21), Adani ×1 (depreciation 5.50 — bogus match on the
BS page). Note: benchmark status counts didn't move for this fix — the
*values* under PROBABLE went from wrong to right. Only the golden gate can
see that class of improvement.

BMW-round per-file deltas: BMW 2V/22M → 14V/8M; Adani 4V/9M → 6V/5M;
Wilmar 0V/3F → 3V/0F; Newgen & HDFC kept earlier gains; Airtel, Reliance,
TCS unchanged. Zero regressions — category-fix rule holding.

# Open targets (value order)

**Golden is saturated (180/180) — the dataset can no longer drive
improvement.** Next moves change the GAME, not the score:

1. **Expand the corpus + golden** — new PDFs outside the 8 (NBFC, PSU,
   small-cap, scanned, pre-2017) are where every roast said the current
   rules will crack. The 36 remaining benchmark MISSINGs are metrics the
   current statements genuinely don't print (or scanned/odd pages).
2. **Unit detection** (crore/lakh/million/thousand — units per file are
   recorded in the golden entry) — the one error class (100× scale) that
   neither gate can catch today.
3. **TCS perf** (~225-350s) — 5× any other file; profile the profiler.
4. Roadmap: cross-extractor voting, OCR path (HDFC scanned sections),
   second-best-score logging for the ~112-synonym set (roast).
3. **Wilmar residue (11 M)** — improved this round (7 V); remaining
   extraction gaps on located statements.
4. **Newgen residue** — unlabeled subtotals; combined profit/TCI line.
5. **BMW residue (8 M)** — total_liabilities derivable (EQ&L − equity);
   eps/depreciation/employee-cost labels; separate comprehensive-income page.
6. **TCS at ~197s** (worsened from ~170s) — 5× slower than any other file;
   informal budget: no file may exceed 2× its round-1 baseline.
7. Roadmap items: cross-extractor voting (Docling), unit detection (crores/
   lakhs/millions — VERIFIED can't catch 100× scale errors!), bank/NBFC schema,
   OCR path for scanned pages (HDFC), measure kerning-fallback false-positive
   surface on notes pages.
