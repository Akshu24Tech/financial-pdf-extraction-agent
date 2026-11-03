"""Evaluate the REAL LLM fallback on the reports in test_pdfs/holdout/.

    set FINAGENT_LLM_PROVIDER=gemini      (or groq)
    set GEMINI_API_KEY=...                (or GROQ_API_KEY)
    python experiments/llm_fallback_eval.py

Not part of CI: it calls a paid/rate-limited API and the answers can vary.
CI tests the fallback's LOGIC with a fake model (tests/test_llm_fallback.py);
this script measures the MODEL.

For every value the LLM got accepted, it checks the number against the
hand-read golden (golden/holdout_golden.json):
    accepted + correct   -> the fallback earned its place
    accepted + wrong     -> the gate failed. Must be 0.
    rejected             -> the model's pick couldn't be proven (stays MISSING)

Caveat: these 4 reports were used to design the fallback, so they are no
longer held out. This measures the mechanism, not generalisation. The honest
number needs a fresh held-out set.
"""

import contextlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finagent.llm_fallback import chooser_from_env
from finagent.pipeline import run

GOLDEN = ROOT / "golden" / "holdout_golden.json"
PDF_DIR = ROOT / "test_pdfs" / "holdout"


def main():
    chooser = chooser_from_env()
    if chooser is None:
        sys.exit("Set FINAGENT_LLM_PROVIDER and the matching API key first (see docstring).")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    (ROOT / "output").mkdir(exist_ok=True)

    totals = {"accepted_correct": 0, "accepted_wrong": 0, "rejected": 0}
    for pdf_name, doc in golden.items():
        if pdf_name.startswith("_"):
            continue
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            report = run(
                PDF_DIR / pdf_name, out_path=ROOT / "output" / "llm_eval.xlsx", chooser=chooser
            )
        metrics = report.to_dict()
        print(f"===== {pdf_name}")
        for line in buf.getvalue().splitlines():
            if line.startswith("[llm]"):
                print("  ", line)
                if "rejected" in line:
                    totals["rejected"] += 1
        for metric, m in metrics.items():
            if "llm" not in m["sources"]:
                continue
            gold = doc["metrics"].get(metric, {}).get("value")
            if gold is None:
                print(f"   ~ {metric}: accepted {m['value']:,.2f} (no golden value to check)")
                continue
            ok = abs(m["value"] - gold) <= 0.01 * abs(gold)
            totals["accepted_correct" if ok else "accepted_wrong"] += 1
            print(
                f"   {'OK' if ok else '!! WRONG'} {metric}: {m['value']:,.2f} vs golden {gold:,.2f}"
            )

    print("\n", totals)
    if totals["accepted_wrong"]:
        print("!! The gate let a wrong value through. Investigate before shipping.")


if __name__ == "__main__":
    main()
