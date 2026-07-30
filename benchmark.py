"""Run the pipeline on every test PDF and print one line per file.

This table is the project's single source of truth: every improvement
must move these numbers, or it didn't help.

    python benchmark.py
"""

import time
import traceback
from pathlib import Path

from finagent.pipeline import run
from finagent.validator import Status

TEST_DIR = Path("test_pdfs")

results = []
for pdf in sorted(TEST_DIR.glob("*.pdf")):
    t0 = time.time()
    try:
        report = run(pdf, verbose=False)
        c = {s: len(report.by_status(s)) for s in Status}
        results.append(
            (
                pdf.name,
                c[Status.VERIFIED],
                c[Status.PROBABLE],
                c[Status.FLAGGED],
                c[Status.DERIVED],
                c[Status.MISSING],
                time.time() - t0,
            )
        )
    except Exception:  # noqa: BLE001
        print(f"{pdf.name}: CRASHED")
        traceback.print_exc()
        results.append((pdf.name, 0, 0, 0, 0, len(Status), time.time() - t0))

print()
print(
    f"{'PDF':<22} {'VERIFIED':>9} {'PROBABLE':>9} {'FLAGGED':>8} "
    f"{'DERIVED':>8} {'MISSING':>8} {'time':>7}"
)
print("-" * 77)
tot = [0, 0, 0, 0, 0]
for name, ver, prob, flag, der, miss, secs in results:
    print(f"{name:<22} {ver:>9} {prob:>9} {flag:>8} {der:>8} {miss:>8} {secs:>6.1f}s")
    tot[0] += ver
    tot[1] += prob
    tot[2] += flag
    tot[3] += der
    tot[4] += miss
print("-" * 77)
print(f"{'TOTAL':<22} {tot[0]:>9} {tot[1]:>9} {tot[2]:>8} {tot[3]:>8} {tot[4]:>8}")
