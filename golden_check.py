"""Ground-truth gate: compare pipeline output against golden/golden.json.

The benchmark proves internal consistency; this proves external correctness.
Mismatches are graded, not binary:

    CORRECT  - within 1% of golden (report rounding)
    SCALE    - ratio is ~a power of 10 (unit/scale error)
    SIGN     - magnitudes match, signs differ
    WRONG    - anything else
    MISSING  - golden value exists, pipeline extracted nothing

The headline number is VERIFIED-but-not-CORRECT: values the validator
proved that are externally wrong. That count should be zero.

    python golden_check.py [pdf-name-substring]
"""
import json
import math
import sys
from pathlib import Path

from finagent.pipeline import run

GOLDEN = Path("golden") / "golden.json"


def grade(extracted, golden):
    if golden == 0:
        return "CORRECT" if abs(extracted) < 1e-9 else "WRONG"
    ratio = extracted / golden
    if abs(ratio - 1) <= 0.01:
        return "CORRECT"
    if abs(-ratio - 1) <= 0.01:
        return "SIGN"
    if ratio > 0:
        log = math.log10(ratio)
        if abs(log - round(log)) <= 0.01 and round(log) != 0:
            return "SCALE"
    return "WRONG"


def main():
    spec = json.loads(GOLDEN.read_text(encoding="utf-8"))
    only = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    rows, ver_wrong = [], []
    for pdf_name, doc in spec.items():
        if pdf_name.startswith("_") or only not in pdf_name.lower():
            continue
        pdf = Path("test_pdfs") / pdf_name
        report = run(pdf, verbose=False).to_dict()
        counts = {"CORRECT": 0, "SCALE": 0, "SIGN": 0, "WRONG": 0, "MISSING": 0}
        for metric, g in doc["metrics"].items():
            v = report.get(metric)
            if v is None or v["value"] is None:
                counts["MISSING"] += 1
                continue
            result = grade(v["value"], g["value"])
            counts[result] += 1
            if result != "CORRECT":
                print(f"  [{result:>5}] {pdf_name} {metric}: "
                      f"extracted {v['value']:,.2f} vs golden {g['value']:,.2f} "
                      f"(status {v['status']}, p{v['page']})")
            if result != "CORRECT" and v["status"] == "VERIFIED":
                ver_wrong.append((pdf_name, metric, v["value"], g["value"]))
        rows.append((pdf_name, len(doc["metrics"]), counts))

    print()
    print(f"{'PDF':<22} {'golden':>6} {'CORRECT':>8} {'SCALE':>6} "
          f"{'SIGN':>5} {'WRONG':>6} {'MISSING':>8}")
    print("-" * 68)
    tot = {"CORRECT": 0, "SCALE": 0, "SIGN": 0, "WRONG": 0, "MISSING": 0}
    n = 0
    for name, total, c in rows:
        print(f"{name:<22} {total:>6} {c['CORRECT']:>8} {c['SCALE']:>6} "
              f"{c['SIGN']:>5} {c['WRONG']:>6} {c['MISSING']:>8}")
        for k in tot:
            tot[k] += c[k]
        n += total
    print("-" * 68)
    print(f"{'TOTAL':<22} {n:>6} {tot['CORRECT']:>8} {tot['SCALE']:>6} "
          f"{tot['SIGN']:>5} {tot['WRONG']:>6} {tot['MISSING']:>8}")
    print()
    print(f"VERIFIED-but-wrong: {len(ver_wrong)}")
    for pdf_name, metric, got, want in ver_wrong:
        print(f"  !! {pdf_name} {metric}: VERIFIED {got:,.2f} but golden {want:,.2f}")


if __name__ == "__main__":
    main()
