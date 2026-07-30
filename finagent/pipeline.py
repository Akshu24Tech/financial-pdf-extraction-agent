"""Pipeline glue: pdf in -> validated metrics -> excel out.

python -m finagent.pipeline test_pdfs\\TCS_2024-2025.pdf
"""

import sys
import time
from pathlib import Path

from . import locator, normalizer, profiler, unit_detector
from .extractors import geometric
from .schema import EXPECTED_METRICS, METRICS, metrics_for_statement
from .validator import Validator


def _extract_basis(pdf_path, locations, log, label):
    """Run extract -> normalize -> validate -> derive for one set of statement
    locations (one basis). Returns (report, {metric: Extraction})."""
    from .deriver import derive

    v = Validator(expected_metrics=EXPECTED_METRICS)
    all_extractions = {}
    for code, loc in locations.items():
        if not loc.page_indices:
            continue
        raw = geometric.extract(
            pdf_path, loc.page_indices, cue_pats=locator.STATEMENT_SIGNATURES[code][1]
        )
        extractions = normalizer.normalize(raw, allowed_metrics=set(metrics_for_statement(code)))
        log(f"[extract:{label}] {code}: {len(raw)} lines -> {len(extractions)} metrics matched")
        for metric, ext in extractions.items():
            if METRICS[metric]["statement"] != code and metric in all_extractions:
                continue
            all_extractions[metric] = ext
            v.add(metric, ext.value, source=ext.source, page=ext.page, label_text=ext.raw_label)

    report = derive(v.validate())
    return report, all_extractions


def _sheet_name(basis):
    return {"consolidated": "Consolidated", "standalone": "Standalone"}.get(basis, "Financials")


def run(pdf_path, out_path=None, verbose=True):
    pdf_path = Path(pdf_path)
    t0 = time.time()

    def log(msg):
        if verbose:
            print(msg)

    # 1. profile
    doc = profiler.profile(pdf_path)
    log(f"[profile] {doc.summary()}")

    # 1b. unit & period anchor engine
    sample_text = " ".join(p.text for p in doc.pages[:15])
    unit_info = unit_detector.detect_unit(sample_text)
    period_info = unit_detector.detect_periods(sample_text)
    log(
        f"[unit_anchor] Scale: {unit_info.unit_name} ({unit_info.currency}) | mult={unit_info.multiplier}"
    )
    log(
        f"[period_anchor] Periods: current='{period_info.current_period}', prior='{period_info.prior_period}'"
    )

    # 3. locate statement pages — PRIMARY (prefers consolidated) plus the
    # standalone/consolidated counterpart, so both are extracted separately.
    primary = locator.locate(doc)
    alternate = locator.locate_alternate(doc, primary)
    for code, loc in primary.items():
        pages_1based = [i + 1 for i in loc.page_indices]
        log(f"[locate] {code}: pages {pages_1based} basis={loc.basis} score={loc.score:.1f}")
        alt = alternate.get(code)
        if alt and alt.page_indices:
            log(
                f"[locate]   alt {code}: pages {[i + 1 for i in alt.page_indices]} "
                f"basis={alt.basis} score={alt.score:.1f}"
            )

    # 4-6b. extract + validate + derive, once per basis. The primary report is
    # the one returned (backward-compatible with the golden/benchmark harness);
    # the alternate is the standalone counterpart, shown on its own sheet.
    primary_basis = primary["BS"].basis if primary.get("BS") else "unknown"
    report, primary_ext = _extract_basis(pdf_path, primary, log, _sheet_name(primary_basis).lower())
    if verbose:
        report.print_summary()

    sheets = [(_sheet_name(primary_basis), report.to_dict(), primary_ext)]
    if locator.has_pages(alternate):
        alt_report, alt_ext = _extract_basis(pdf_path, alternate, log, "standalone")
        sheets.append(
            (
                _sheet_name(
                    alternate["BS"].basis
                    if alternate.get("BS") and alternate["BS"].page_indices
                    else "standalone"
                ),
                alt_report.to_dict(),
                alt_ext,
            )
        )

    # 7. write — one sheet per basis
    if out_path is None:
        out_path = pdf_path.with_suffix("").name + "_metrics.xlsx"
        out_path = Path("output") / out_path
        out_path.parent.mkdir(exist_ok=True)
    from .writer import write_excel

    write_excel(
        sheets, out_path, meta=f"{pdf_path.name} - extracted {time.strftime('%Y-%m-%d %H:%M')}"
    )
    log(f"[write] {out_path}  ({time.time() - t0:.1f}s)")
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
