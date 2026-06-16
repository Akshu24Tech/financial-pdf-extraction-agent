"""Pipeline glue: pdf in -> validated metrics -> excel out.

    python -m finagent.pipeline test_pdfs\\TCS_2024-2025.pdf
"""
import sys
import time
from pathlib import Path

from . import profiler, locator, normalizer
from .extractors import geometric
from .schema import EXPECTED_METRICS, metrics_for_statement
from .validator import Validator


def run(pdf_path, out_path=None, verbose=True):
    pdf_path = Path(pdf_path)
    t0 = time.time()

    def log(msg):
        if verbose:
            print(msg)

    # 1. profile
    doc = profiler.profile(pdf_path)
    log(f"[profile] {doc.summary()}")

    # 3. locate statement pages
    locations = locator.locate(doc)
    for code, loc in locations.items():
        pages_1based = [i + 1 for i in loc.page_indices]
        log(f"[locate] {code}: pages {pages_1based} basis={loc.basis} score={loc.score:.1f}")

    # 4. extract + 5. normalize, statement by statement so labels can only
    # match metrics that belong on that statement
    v = Validator(expected_metrics=EXPECTED_METRICS)
    all_extractions = {}
    for code, loc in locations.items():
        if not loc.page_indices:
            continue
        raw = geometric.extract(pdf_path, loc.page_indices,
                                cue_pats=locator.STATEMENT_SIGNATURES[code][1])
        extractions = normalizer.normalize(raw, allowed_metrics=set(metrics_for_statement(code)))
        log(f"[extract] {code}: {len(raw)} lines -> {len(extractions)} metrics matched")
        for metric, ext in extractions.items():
            all_extractions[metric] = ext
            v.add(metric, ext.value, source=ext.source, page=ext.page,
                  label_text=ext.raw_label)

    # 6. validate, then 6b. derive what the identities fix exactly.
    # Order matters: derived values must never feed the identity proofs —
    # they satisfy the deriving identity by construction.
    report = v.validate()
    from .deriver import derive
    report = derive(report)
    if verbose:
        report.print_summary()

    # 7. write
    if out_path is None:
        out_path = pdf_path.with_suffix("").name + "_metrics.xlsx"
        out_path = Path("output") / out_path
        out_path.parent.mkdir(exist_ok=True)
    from .writer import write_excel
    write_excel(report.to_dict(), out_path, extractions=all_extractions,
                meta=f"{pdf_path.name} - extracted {time.strftime('%Y-%m-%d %H:%M')}")
    log(f"[write] {out_path}  ({time.time() - t0:.1f}s)")
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
