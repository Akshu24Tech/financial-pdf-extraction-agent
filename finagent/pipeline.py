"""Pipeline glue: pdf in -> validated metrics -> excel out.

python -m finagent.pipeline test_pdfs\\TCS_2024-2025.pdf
"""

import sys
import time
from pathlib import Path

from . import locator, normalizer, profiler, unit_detector
from .extractors import geometric
from .schema import EXPECTED_METRICS, METRICS, metrics_for_statement
from .tracing import flush_tracing, trace_span, wrap_agent


def _extract_basis(pdf_path, locations, log, label, chooser=None):
    """Run extract -> normalize -> validate (+ LLM fallback) -> derive for one
    set of statement locations (one basis). Returns (report, {metric: Extraction})."""
    from .deriver import derive
    from .llm_fallback import LLM_SOURCE, fill_missing
    from .normalizer import Extraction

    observations, all_extractions, raw_by_statement = [], {}, {}
    for code, loc in locations.items():
        if not loc.page_indices:
            continue
        raw = geometric.extract(
            pdf_path,
            loc.page_indices,
            cue_pats=locator.STATEMENT_SIGNATURES[code][1],
            want_basis=label,
        )
        raw_by_statement[code] = raw
        extractions = normalizer.normalize(raw, allowed_metrics=set(metrics_for_statement(code)))
        log(f"[extract:{label}] {code}: {len(raw)} lines -> {len(extractions)} metrics matched")
        for metric, ext in extractions.items():
            if METRICS[metric]["statement"] != code and metric in all_extractions:
                continue
            all_extractions[metric] = ext
            observations.append((metric, ext.value, ext.source, ext.page, ext.raw_label))

    validation, accepted = fill_missing(
        observations, raw_by_statement, EXPECTED_METRICS, chooser, log=log
    )
    for metric, (value, page, raw_label) in accepted.items():
        all_extractions[metric] = Extraction(
            metric=metric,
            value=value,
            raw_label=raw_label,
            page=page,
            source=LLM_SOURCE,
            score=0.0,
            extra_values=[],
        )
    report = derive(validation)
    return report, all_extractions


def _sheet_name(basis):
    return {"consolidated": "Consolidated", "standalone": "Standalone"}.get(basis, "Financials")


def run(pdf_path, out_path=None, verbose=True, chooser="env"):
    """chooser: the LLM fallback for MISSING metrics. "env" (default) reads
    FINAGENT_LLM_PROVIDER; None turns it off; tests pass a fake."""
    if chooser == "env":
        from .llm_fallback import chooser_from_env

        chooser = chooser_from_env()
    pdf_path = Path(pdf_path)
    t0 = time.time()

    def log(msg):
        if verbose:
            print(msg)

    with wrap_agent("financial-pdf-extraction-agent") as agent_run:
        agent_run.set_input(
            {
                "pdf_path": str(pdf_path),
                "out_path": str(out_path) if out_path is not None else None,
            }
        )

        # 1. profile
        with trace_span("pdf_profile", kind="trace"):
            doc = profiler.profile(pdf_path)
            log(f"[profile] {doc.summary()}")

        # 1b. unit & period anchor engine
        with trace_span("unit_period_detection", kind="trace"):
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
        with trace_span("locate_pages", kind="trace"):
            primary = locator.locate(doc)
            alternate = locator.locate_alternate(doc, primary)
            for code, loc in primary.items():
                pages_1based = [i + 1 for i in loc.page_indices]
                log(
                    f"[locate] {code}: pages {pages_1based} basis={loc.basis} score={loc.score:.1f}"
                )
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
        primary_label = _sheet_name(primary_basis).lower()
        with trace_span(f"extract_basis_{primary_label}", kind="tool"):
            report, primary_ext = _extract_basis(pdf_path, primary, log, primary_label, chooser)
        if verbose:
            report.print_summary()

        sheets = [(_sheet_name(primary_basis), report.to_dict(), primary_ext)]
        if locator.has_pages(alternate):
            alt_basis = (
                alternate["BS"].basis
                if alternate.get("BS") and alternate["BS"].page_indices
                else "standalone"
            )
            with trace_span(f"extract_basis_{alt_basis}", kind="tool"):
                alt_report, alt_ext = _extract_basis(pdf_path, alternate, log, alt_basis, chooser)
            sheets.append((_sheet_name(alt_basis), alt_report.to_dict(), alt_ext))

            # Build Side-by-Side Comparison dict
            comp_dict = {}
            primary_dict = report.to_dict()
            alt_dict = alt_report.to_dict()

            consol_d = primary_dict if primary_label == "consolidated" else alt_dict
            stand_d = alt_dict if primary_label == "consolidated" else primary_dict

            for metric in METRICS:
                c_v = consol_d.get(metric, {})
                s_v = stand_d.get(metric, {})
                c_val = c_v.get("value")
                s_val = s_v.get("value")
                diff = (c_val - s_val) if (c_val is not None and s_val is not None) else None

                comp_dict[metric] = {
                    "consolidated_value": c_val,
                    "standalone_value": s_val,
                    "difference": diff,
                    "consolidated_status": c_v.get("status", "MISSING"),
                    "standalone_status": s_v.get("status", "MISSING"),
                    "consolidated_page": c_v.get("page"),
                    "standalone_page": s_v.get("page"),
                }

            sheets.insert(0, ("Side-by-Side", comp_dict, None))

        # 7. write — one sheet per basis
        if out_path is None:
            out_path = pdf_path.with_suffix("").name + "_metrics.xlsx"
            out_path = Path("output") / out_path
            out_path.parent.mkdir(exist_ok=True)
        from .writer import write_excel

        with trace_span("write_excel", kind="tool"):
            write_excel(
                sheets,
                out_path,
                meta=f"{pdf_path.name} - extracted {time.strftime('%Y-%m-%d %H:%M')}",
            )
        log(f"[write] {out_path}  ({time.time() - t0:.1f}s)")

        agent_run.set_output(
            {
                "status": "success",
                "pdf_name": pdf_path.name,
                "out_path": str(out_path),
                "primary_basis": primary_basis,
                "sheets": [s[0] for s in sheets],
                "metrics_extracted": len(primary_ext),
                "execution_time_seconds": round(time.time() - t0, 2),
            }
        )
        flush_tracing()
        return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
