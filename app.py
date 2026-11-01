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

if uploaded is None:
    st.info("Upload a PDF to start. Large reports (300+ pages) can take a few minutes.")
    st.stop()

with st.spinner("Profiling → locating statements → extracting → validating…"):
    try:
        metrics, excel_bytes = extract(uploaded.getvalue(), uploaded.name)
    except Exception as e:  # noqa: BLE001 — show a readable error, not a stack trace
        st.error(f"Extraction failed: {e}")
        st.stop()

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

st.download_button(
    "⬇️ Download Excel (with page + check columns)",
    data=excel_bytes,
    file_name=Path(uploaded.name).stem + "_metrics.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
