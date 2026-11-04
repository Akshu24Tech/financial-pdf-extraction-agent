# Why the Airtel sample shows 2 FLAGGED metrics

Interview prep. The flag is **correct behaviour**, not a bug — the system refuses
to silently equate two numbers the report itself defines differently. This note
explains what to say when someone clicks the flag.

## The two flagged metrics

Both fail the **same** cross-statement check,
`closing_cash_ties_to_balance_sheet`:

- `cash_and_equivalents` = **61,056** (balance sheet, Note 15, p199)
- `closing_cash` = **106,531** (cash-flow statement, p201)
- Gap = **45,475**

## The real numbers (Bharti Airtel FY2024-25)

| Source | Line | Value |
|---|---|---|
| Balance sheet, Note 15 (p199) | Cash and cash equivalents | **61,056** |
| Balance sheet, Note 15 (p199) | Other bank balances | 106,143 |
| Cash-flow statement (p201) | Cash & cash equivalents at **end of year** (refer Note 15) | **106,531** |

The cash-flow statement reconciles internally, so 106,531 is solid:

```
beginning 90,521 + net increase 15,292 + FX effect 718 = 106,531 ✓
```

It just isn't the same thing as the 61,056 balance-sheet line.

## Why they differ

The two statements use **different definitions of "cash."** Under **Ind AS 7**
(India's IFRS cash-flow standard), "cash and cash equivalents" for the
*cash-flow statement* includes short-term, highly liquid items — bank deposits
with ≤3-month maturity and liquid investments — that the *balance sheet* reports
on a separate line (here, "Other bank balances," 106,143).

So the cash-flow closing figure is the 61,056 balance-sheet cash **plus ~45,475
of those liquid balances** that count as cash equivalents for cash-flow purposes
but not for the balance-sheet "Cash and cash equivalents" caption.

## One-line answer for an interviewer

> The cash-flow statement's closing cash (106,531) is broader than the
> balance-sheet "Cash and cash equivalents" line (61,056). Ind AS 7 folds
> short-term liquid deposits/investments into cash for the cash-flow statement
> that the balance sheet reports separately under "Other bank balances." Both
> figures are right; my cross-statement check flags the mismatch precisely
> *because* a naive "closing cash = balance-sheet cash" rule doesn't hold here,
> and a human confirms it's the definitional gap, not an extraction error.

## Honest caveat

The three figures and the Ind AS 7 mechanism are confirmed. The exact sub-items
that sum to the 45,475 reconciling amount live inside the Note 15 detail and
have **not** been pinned line-by-line — say "a portion of other bank balances /
short-term liquid investments" rather than naming a specific figure, unless you
verify the note first.

---

*Source pages: Airtel FY2024-25 annual report — balance sheet / Note 15 (p199),
standalone-basis cash-flow statement (p201). Metrics as extracted into
`samples/airtel_fy25.json`.*
