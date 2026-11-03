# Held-out evaluation — first blind run (2026-11-03)

**Question this answers:** the golden set scores 180/180, but every rule in the
pipeline was tuned on those same reports. What happens on a PDF the system has
never seen?

**Rules followed**
- 4 annual reports chosen *before* running anything, none used in development.
- One run, at commit `dd3a625`, no code changes after seeing the output.
- Output frozen in [`golden/holdout_blind_2026-11-03.json`](../golden/holdout_blind_2026-11-03.json).
  It is never regenerated. Fixes inspired by it are measured on a *new* held-out set.
- Ground truth read from rendered page images (not the text layer the pipeline
  parses) into [`golden/holdout_golden.json`](../golden/holdout_golden.json), with
  accounting identities checked per statement. Graded with `python holdout_check.py`.

## The set

| Report | Why it's in the set | Unit |
|---|---|---|
| ICICI Bank FY2024-25 | Bank: different statement format | INR thousand ('000s) |
| Shivalik Bimetal Controls | Small-cap, less polished layout | INR lakh |
| Hindustan Unilever FY2025-26 | Large-cap with continuing + discontinued operations | INR crore |
| BSE Ltd FY2025-26 | Exchange: unusual income structure | INR lakh |

## Result 1: status scorecard (28 metrics per report)

| Report | Time | VERIFIED | DERIVED | PROBABLE | FLAGGED | MISSING |
|---|---|---|---|---|---|---|
| BSE | 47s | 4 | 2 | 14 | 5 | 3 |
| Hindustan Unilever | 74s | 13 | 1 | 10 | 0 | 4 |
| ICICI Bank | 72s | 5 | 0 | 6 | 0 | 17 |
| Shivalik Bimetal | 45s | 8 | 2 | 13 | 0 | 5 |
| **Total (112)** | | **30** | **5** | **43** | **5** | **29** |

- **VERIFIED: 30/112 = 27%**, versus about 46% (100 of 218) in the development
  set's last benchmark. The gap is the honest cost of tuning on 8 reports.
- **Proven (VERIFIED + DERIVED): 35/112 = 31%.**
- **Extracted something: 83/112 = 74%.**
- **No crashes**, every statement page located, all runs under 75s.

## Result 2: correctness vs hand-read golden

48 headline values (12 per report), graded by `python holdout_check.py`:

| Report | CORRECT | WRONG | MISSING | ABSENT_OK |
|---|---|---|---|---|
| BSE | 11 | 0 | 1 | 0 |
| Hindustan Unilever | 9 | 0 | 3 | 0 |
| ICICI Bank | 6 | 0 | 2 | 4 |
| Shivalik Bimetal | 9 | 0 | 3 | 0 |
| **Total** | **35** | **0** | **9** | **4** |

- **VERIFIED-but-wrong: 0.** No number the validator vouched for was wrong.
- **0 WRONG, 0 SCALE, 0 SIGN, 0 INVENTED.** Every headline value FinAgent
  extracted was correct. Every failure was a MISSING: it stayed silent rather
  than guessing.
- **Accuracy 39/48 = 81%** (35 correct + 4 correctly absent on the bank).
- **FLAGGED-but-correct (false alarms): 5, all BSE.** Real but costly: a reviewer
  would check 5 numbers that were right (see item 5 below).
- Outside the headline 12, two real errors were found while reading:
  - BSE `finance_costs` = 3 is the **prior-year** column; current year prints 16.
    Status was PROBABLE, so the system never claimed it was proven.
  - BSE `total_liabilities` was DERIVED as total assets minus equity (6,65,064),
    which silently swallows BSE's core settlement guarantee fund (1,24,683), a
    separate block that is neither equity nor liability. Printed liabilities
    sum to 5,40,381. **A DERIVED value can be wrong when the balance sheet has a
    block the identity doesn't model.**

**Golden caveat:** the values were read from rendered page images (not the text
layer FinAgent parses) with identities checked per statement, but the reader had
seen FinAgent's output first, so this is not a fully independent golden. Spot-check
before quoting it as final.

## What broke, and why

1. **Profit lines carry extra words, and 3 of 4 reports lost net profit.**
   Of the 9 headline misses, 6 are profit or tax lines and 3 are cash lines.
   - Shivalik: `IX Profit before tax (VII-VIII)`, `XI Profit for the years (IX-X)`
     (roman-numeral prefix, formula suffix, and a typo in the report itself).
   - BSE: `Net profit for the year from continuing operation (7-8)`.
   - Shivalik's closing cash: `...at the closing of year` instead of `...at the end of the year`.
   - The vocabulary matches clean labels; real reports decorate them.
2. **Continuing vs discontinued operations (HUL).** There is no plain "profit
   before tax" line: profit is split A (continuing) + B (discontinued) = C.
   The schema has no concept of this split yet.
3. **Two-column statement page (HUL).** The P&L and the other-comprehensive-income
   block are printed side by side, so lines merge:
   `Other income 28 751 1,017 Tax on above 9A (2) 5`.
4. **Bank format (ICICI): 17 of 28 MISSING.** Of the headline 12, 4 are genuinely
   not printed by a bank (total equity, cash as one line, PBT, tax) and FinAgent
   correctly left them empty; it missed operating cash flow and closing cash.
   Banks have no current/non-current split, no profit-before-tax line, and use
   schedules (interest earned, deposits, capital and reserves). Even with the HDFC
   bank vocabulary from development, this layout mostly didn't match. No unit was
   detected on the P&L page either.
5. **BSE: 5 FLAGGED, all confirmed false alarms (identity gaps, not misreads).**
   - `total_income_buildup` assumes total income = revenue + other income. BSE
     prints a third line, *Investment income* 29,030:
     4,83,395 + 29,030 + 2,385 = 5,14,810. All three extracted values are correct.
   - `closing_cash_ties_to_balance_sheet` fails (1,67,159 vs 1,64,642) because
     cash-flow cash excludes earmarked balances (unpaid dividend, SGF etc.), and
     the report reconciles the difference on the same page. Both values are correct.
   - The system *refused to vouch* for numbers it couldn't reconcile, which is the
     safe failure. But the identities assume a simpler world than real reports.

## Also found

- `golden_check.py` grades within **1%** as CORRECT. Reports print exact figures,
  so a 0.94% error (about 600 lakh on Shivalik's total assets) would pass as
  correct. The validator itself uses 0.5%. Worth tightening for exact matches.

## What this means

- **The verifier generalises: 0 VERIFIED-but-wrong, 0 WRONG on unseen reports.**
  When FinAgent didn't know, it said nothing. That's the property that matters
  most for financial data.
- **Its weaknesses are coverage and false alarms**, both visible and fixable:
  9 MISSING headline values and 5 FLAGGED-but-correct.
- Extraction coverage does not generalise as well as the dev score suggested.
  The main gaps are label normalisation, continuing/discontinued operations, and
  banks.
- Next held-out set (after fixes): another bank, an older (2016-18) report, and a
  scanned PDF.
