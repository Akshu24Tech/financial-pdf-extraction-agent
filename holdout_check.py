"""Grade the FROZEN blind run on the held-out PDFs against hand-read golden values.

    python holdout_check.py

Why this does NOT re-run the pipeline (unlike golden_check.py): the held-out
score is only honest for the first run. Once we've seen these PDFs and changed
code because of them, they are no longer held out. So we grade the frozen
output of that first run, forever. Improvements get measured on a NEW held-out
set.

Grades (same as golden_check.py, plus two for metrics the report never prints):
    CORRECT     within 1% of golden
    SCALE       off by a power of 10 (unit error)
    SIGN        right magnitude, wrong sign
    WRONG       anything else
    MISSING     golden value exists, pipeline extracted nothing
    ABSENT_OK   report doesn't print it, pipeline extracted nothing (correct)
    INVENTED    report doesn't print it, pipeline extracted a value anyway

Headline: VERIFIED-but-wrong, i.e. values the validator proved that are
externally wrong. That number should be zero.
Second number: FLAGGED-but-correct, i.e. false alarms. Not dangerous, but each
one costs a reviewer time and erodes trust in the flags.
"""

import json
from pathlib import Path

from golden_check import grade

BLIND = Path("golden") / "holdout_blind_2026-11-03.json"
GOLDEN = Path("golden") / "holdout_golden.json"
GRADES = ["CORRECT", "SCALE", "SIGN", "WRONG", "MISSING", "ABSENT_OK", "INVENTED"]


def grade_one(extracted, gold):
    if gold.get("not_printed"):
        return "ABSENT_OK" if extracted is None else "INVENTED"
    if extracted is None:
        return "MISSING"
    return grade(extracted, gold["value"])


def main():
    blind = json.loads(BLIND.read_text(encoding="utf-8"))
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    rows, ver_wrong, flag_right, unfilled = [], [], [], []
    for pdf, doc in golden.items():
        if pdf.startswith("_"):
            continue
        run = blind[pdf]["metrics"]
        counts = dict.fromkeys(GRADES, 0)
        for metric, gold in doc["metrics"].items():
            if gold.get("value") is None and not gold.get("not_printed"):
                unfilled.append(f"{pdf}: {metric}")
                continue
            got = run.get(metric, {})
            result = grade_one(got.get("value"), gold)
            counts[result] += 1
            if result not in ("CORRECT", "ABSENT_OK"):
                shown = f"{got['value']:,.2f}" if got.get("value") is not None else "-"
                want = "not printed" if gold.get("not_printed") else f"{gold['value']:,.2f}"
                print(
                    f"  [{result:>9}] {pdf} {metric}: got {shown} vs golden {want}"
                    f" (status {got.get('status', 'MISSING')})"
                )
            if got.get("status") == "VERIFIED" and result not in (
                "CORRECT",
                "ABSENT_OK",
            ):
                ver_wrong.append(f"{pdf} {metric}")
            if got.get("status") == "FLAGGED" and result == "CORRECT":
                flag_right.append(f"{pdf} {metric}")
        rows.append((pdf, counts))

    if unfilled:
        print(f"\n{len(unfilled)} golden values still unfilled (skipped):")
        for u in unfilled:
            print(f"  - {u}")

    print(f"\n{'PDF':<32}" + "".join(f"{g:>10}" for g in GRADES))
    print("-" * (32 + 10 * len(GRADES)))
    total = dict.fromkeys(GRADES, 0)
    for pdf, c in rows:
        print(f"{pdf:<32}" + "".join(f"{c[g]:>10}" for g in GRADES))
        for g in GRADES:
            total[g] += c[g]
    print("-" * (32 + 10 * len(GRADES)))
    print(f"{'TOTAL':<32}" + "".join(f"{total[g]:>10}" for g in GRADES))

    graded = sum(total.values())
    if graded:
        right = total["CORRECT"] + total["ABSENT_OK"]
        print(f"\nAccuracy on graded values: {right}/{graded} = {right / graded:.0%}")
    print(f"VERIFIED-but-wrong: {len(ver_wrong)}")
    for v in ver_wrong:
        print(f"  !! {v}")
    print(f"FLAGGED-but-correct (false alarms): {len(flag_right)}")
    for v in flag_right:
        print(f"  ?? {v}")


if __name__ == "__main__":
    main()
