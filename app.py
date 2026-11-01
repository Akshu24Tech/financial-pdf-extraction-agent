"""FinAgent web demo — upload an annual-report PDF, see every number with its proof.

Run locally:
    pip install streamlit
    streamlit run app.py

Design notes (know these for the interview):
- This file is a THIN UI layer. All logic lives in finagent.pipeline.run();
  the UI only calls it and displays the result. Same engine as the CLI,
  so the demo can never disagree with the tests.
- Uploads are written to a temp dir, never kept. Annual reports are
  copyrighted, so we don't store them.
- st.cache_data keys on the file bytes: re-uploading the same PDF returns
  instantly instead of re-running a 30-200s extraction.
"""

import json
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from finagent.pipeline import run

# Status -> (emoji, background colour). Matches the Excel colour scheme.
STATUS_STYLE = {
    "VERIFIED": ("🟢", "#d1fae5"),
    "DERIVED": ("🔵", "#dbeafe"),
    "PROBABLE": ("🟡", "#fef9c3"),
    "FLAGGED": ("🔴", "#fee2e2"),
    "MISSING": ("⬜", "#f3f4f6"),
}
STATUS_ORDER = ["VERIFIED", "DERIVED", "PROBABLE", "FLAGGED", "MISSING"]

STATUS_MEANING = {
    "VERIFIED": "Passed at least one accounting identity check.",
    "DERIVED": "Not printed, but computed exactly from verified numbers.",
    "PROBABLE": "Extracted, but no rule could check it.",
    "FLAGGED": "Broke an accounting identity. Needs a human.",
    "MISSING": "Not found in the report.",
}


SAMPLE_PATH = Path(__file__).parent / "samples" / "airtel_fy25.json"

# A large annual report can exhaust a free hosting tier's RAM mid-extraction and
# kill the process. Set FINAGENT_MAX_UPLOAD_MB (e.g. 8) on the host to reject
# oversized uploads gracefully; unset (0) means no limit, for local use.
MAX_UPLOAD_MB = int(os.getenv("FINAGENT_MAX_UPLOAD_MB", "0"))


@st.cache_data(show_spinner=False)
def load_sample() -> dict:
    """Precomputed result for one report, so the hosted demo is instant and
    needs no copyrighted PDF on the server. The numbers are facts from a public
    annual report; the PDF itself is never shipped."""
    return json.loads(SAMPLE_PATH.read_text())


@st.cache_data(show_spinner=False, max_entries=5)
def extract(pdf_bytes: bytes, filename: str):
    """Run the full pipeline on uploaded bytes. Returns (metrics_dict, excel_bytes)."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / filename
        pdf_path.write_bytes(pdf_bytes)
        out_path = Path(tmp) / "metrics.xlsx"
        report = run(pdf_path, out_path=out_path, verbose=False)
        return report.to_dict(), out_path.read_bytes()


def human_page(page_index):
    """The pipeline stores 0-based page indices; people read 1-based page numbers."""
    return page_index + 1 if page_index is not None else None


def to_table(metrics: dict) -> pd.DataFrame:
    rows = []
    for name, m in metrics.items():
        rows.append(
            {
                "Status": f"{STATUS_STYLE[m['status']][0]} {m['status']}",
                "Metric": name.replace("_", " ").title(),
                "Value": m["value"],
                "Page": human_page(m["page"]),
                "Checks passed": len(m["checks_passed"]),
                "Checks failed": len(m["checks_failed"]),
                "_order": STATUS_ORDER.index(m["status"]),
            }
        )
    df = pd.DataFrame(rows).sort_values(["_order", "Metric"]).drop(columns="_order")
    return df.reset_index(drop=True)


def colour_row(row):
    status = row["Status"].split(" ", 1)[1]
    return [f"background-color: {STATUS_STYLE[status][1]}; color: #111"] * len(row)


# ---------------------------------------------------------------- page ------
st.set_page_config(page_title="FinAgent", page_icon="📊", layout="wide")

st.title("📊 FinAgent")
st.markdown(
    "**Financial statement extraction that proves its own numbers.** "
    "Upload an annual report. Every value is checked against accounting "
    "identities (Assets = Liabilities + Equity, closing cash ties, subtotals add up) "
    "before you see it."
)

with st.expander("What do the statuses mean?"):
    for s in STATUS_ORDER:
        st.markdown(f"{STATUS_STYLE[s][0]} **{s}**: {STATUS_MEANING[s]}")

uploaded = st.file_uploader("Annual report PDF", type="pdf")

# Sample mode: a one-click precomputed result, so recruiters see the full
# output without a live 30-200s run. A real upload always overrides it.
if "use_sample" not in st.session_state:
    st.session_state.use_sample = False
if st.button("▶ Try a sample — Bharti Airtel FY2024-25") and SAMPLE_PATH.exists():
    st.session_state.use_sample = True
if uploaded is not None:
    st.session_state.use_sample = False

if uploaded is None and not st.session_state.use_sample:
    st.info("Upload a PDF to start, or try the sample. Large reports (300+ pages) can take a few minutes.")
    st.stop()

if st.session_state.use_sample and uploaded is None:
    metrics = load_sample()
    excel_bytes = None
    source_name = "Bharti_Airtel_FY25"
    st.success("Sample result — precomputed from Bharti Airtel's public FY2024-25 annual report. Upload your own PDF above to run the live pipeline.")
else:
    size_mb = uploaded.size / 1_000_000
    if MAX_UPLOAD_MB and size_mb > MAX_UPLOAD_MB:
        st.warning(
            f"This PDF is {size_mb:.0f} MB. The hosted demo caps uploads at "
            f"{MAX_UPLOAD_MB} MB, because a large annual report can exhaust this "
            "free tier's memory mid-extraction. Click **Try a sample** above for a "
            "full result, or run the app locally (`streamlit run app.py`) for "
            "full-size files — there's no limit there."
        )
        st.stop()
    with st.spinner("Profiling → locating statements → extracting → validating…"):
        try:
            metrics, excel_bytes = extract(uploaded.getvalue(), uploaded.name)
        except Exception as e:  # noqa: BLE001 — show a readable error, not a stack trace
            st.error(f"Extraction failed: {e}")
            st.stop()
    source_name = Path(uploaded.name).stem

# ---------------------------------------------------------------- summary ---
counts = {s: sum(1 for m in metrics.values() if m["status"] == s) for s in STATUS_ORDER}
cols = st.columns(len(STATUS_ORDER))
for col, s in zip(cols, STATUS_ORDER):
    col.metric(f"{STATUS_STYLE[s][0]} {s}", counts[s])

trusted = counts["VERIFIED"] + counts["DERIVED"]
st.caption(f"{trusted} of {len(metrics)} metrics are proven by accounting identities.")

# ---------------------------------------------------------------- table -----
df = to_table(metrics)
st.dataframe(
    df.style.apply(colour_row, axis=1).format({"Value": "{:,.2f}", "Page": "{:.0f}"}, na_rep="—"),
    use_container_width=True,
    hide_index=True,
)

# ---------------------------------------------------------------- receipts --
st.subheader("Receipts")
st.caption("Why each number is trusted (or not).")
for name, m in sorted(metrics.items(), key=lambda kv: STATUS_ORDER.index(kv[1]["status"])):
    if m["status"] == "MISSING":
        continue
    label = f"{STATUS_STYLE[m['status']][0]} {name.replace('_', ' ').title()}"
    with st.expander(label):
        st.write(f"**Value:** {m['value']:,.2f}  |  **Page:** {human_page(m['page'])}")
        if m["sources"]:
            st.write("**Source:** " + ", ".join(m["sources"]))
        for c in m["checks_passed"]:
            st.write(f"✅ {c}")
        for c in m["checks_failed"]:
            st.write(f"❌ {c}")

if excel_bytes is not None:
    st.download_button(
        "⬇️ Download Excel (with page + check columns)",
        data=excel_bytes,
        file_name=source_name + "_metrics.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.caption("Upload your own PDF to download the Excel workbook with page and check columns.")
