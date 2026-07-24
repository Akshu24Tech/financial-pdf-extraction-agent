# Project Decisions, Architecture & Activity Logs

This document maintains a comprehensive record of all architectural decisions, design rationale, benchmark results, CI/CD pipeline structures, and project development logs for the **Financial PDF Extraction Agent (`finagent`)**.

---

## 1. System Architecture & 7-Stage Assembly Line

The core thesis of this project is: **Accuracy comes from verification, not extraction.**

Financial statements are self-verifying systems ($Assets = Liabilities + Equity$). The pipeline operates as a 7-stage assembly line:

```
    PDF Report
        │
        ▼
┌───────────────┐   1. PROFILE (finagent/profiler.py)
│  1. PROFILE   │   Lightweight 1-second pre-flight scan (pypdf). Measures page
└───────────────┘   dimensions, orientation (/Rotate), text quality (OK/SUSPECT/EMPTY).
        │
        ▼
┌───────────────┐   2. GEOMETRY (finagent/geometry.py)
│  2. GEOMETRY  │   Detects wide A3 sheets ("Two-Up" side-by-side pages like Airtel/Reliance)
└───────────────┘   and splits them into single logical pages before coordinate extraction.
        │
        ▼
┌───────────────┐   3. LOCATE (finagent/locator.py)
│  3. LOCATE    │   Discovers Consolidated & Standalone statement pages (BS, PL, CF)
└───────────────┘   using signature cue matching.
        │
        ▼
┌───────────────┐   4. EXTRACT (finagent/extractors/geometric.py)
│  4. EXTRACT   │   Borderless-table safe row extraction using pdfplumber bounding boxes
└───────────────┘   strictly on located statement pages.
        │
        ▼
┌───────────────┐   5. NORMALIZE (finagent/normalizer.py & schema.py & unit_detector.py)
│  5. NORMALIZE │   Parses numbers, strips note/page reference columns (e.g. Note 14),
└───────────────┘   detects table units (₹ in Crores, USD Millions), and aligns labels.
        │
        ▼
┌───────────────┐   6. VALIDATE & DERIVE (finagent/validator.py & deriver.py)
│ 6. VALIDATION │   Proves numbers using accounting identities and cross-statement cash ties.
└───────────────┘   Derives missing metrics satisfying identities. (Status: 🟢 VERIFIED / 🟡 PROBABLE / 🔴 FLAGGED)
        │
        ▼
┌───────────────┐   7. WRITE (finagent/writer.py)
│   7. WRITE    │   Generates audit-ready Excel workbooks with trust badges, page citations,
└───────────────┘   and check receipts.
        │
        ▼
   metrics.xlsx
```

---

## 2. Key Architectural Decisions & Rationale

### Decision 1: Pre-Flight Document Profiling (`profiler.py`)
- **Problem**: Running heavy coordinate table extraction (`pdfplumber`) on a 600-page annual report takes 5+ minutes and consumes ~1.5 GB RAM.
- **Decision**: Use `pypdf` for a 1-second full-document pass. Profile text quality (`OK`, `SUSPECT`, `EMPTY`), detect sideways pages (`/Rotate`), and calculate `landscape_ratio`.
- **Benefit**: Pinpoints the 6 statement pages first so heavy extraction runs ONLY on those 6 pages — saving 99% CPU and RAM.

### Decision 2: In-Package CLI & Single-File Bundler (`cli.py` & `bundler.py`)
- **Problem**: Loose top-level scripts create clutter and risk single-file distribution drift (`finagent_single.py` falling out of sync with `finagent/`).
- **Decision**: Integrated `finagent/cli.py` and `finagent/bundler.py` directly inside the package. Registered `finagent = "finagent.cli:main"` in `pyproject.toml`.
- **Benefit**: Allows running `finagent run`, `finagent benchmark`, `finagent golden`, and `finagent build-single`. CI enforces sync via `python -m finagent.bundler --check`.

### Decision 3: Unit & Period Anchor Engine (`unit_detector.py`)
- **Problem**: Financial reports express numbers in varying units (*₹ in Crores*, *₹ in Lakhs*, *USD Millions*, *€ Millions*, *Rs in Thousands*) and comparative columns (`FY25` vs `FY24`).
- **Decision**: Added automated header scanning in `unit_detector.py` to extract scale multipliers and anchor period dates.

---

## 3. Benchmark & Ground-Truth Verification Results

Ran ground-truth verification gate (`golden_check.py`) across 10 corporate annual reports:

| PDF Name | Golden Metrics | CORRECT | SCALE | SIGN | WRONG | MISSING |
|---|---|---|---|---|---|---|
| **TCS_2024-2025.pdf** | 27 | 27 | 0 | 0 | 0 | 0 |
| **Reliance.pdf** | 27 | 27 | 0 | 0 | 0 | 0 |
| **Airtel_2024-25.pdf** | 26 | 26 | 0 | 0 | 0 | 0 |
| **BMW-2025.pdf** | 22 | 22 | 0 | 0 | 0 | 0 |
| **Adani_FY25.pdf** | 28 | 23 | 0 | 0 | 4 | 1 |
| **Newgen.pdf** | 14 | 14 | 0 | 0 | 0 | 0 |
| **HDFC.pdf** | 14 | 14 | 0 | 0 | 0 | 0 |
| **Wilmar.pdf** | 22 | 22 | 0 | 0 | 0 | 0 |
| **BHEL_2024-25.pdf** | 27 | 26 | 0 | 0 | 1 | 0 |
| **Bajaj-Finance-2025.pdf** | 23 | 19 | 0 | 0 | 2 | 2 |
| **TOTAL** | **230** | **220** | **0** | **0** | **7** | **3** |

- **Overall Accuracy**: **95.6%** (220 / 230 correct)
- **VERIFIED-but-Wrong**: **0** (Zero confident-but-wrong values across the entire test suite).

---

## 4. CI/CD Pipeline Setup

- **CI Workflow (`.github/workflows/ci.yml`)**:
  - Matrix testing across Python `3.11`, `3.12`, `3.13`.
  - Code linting via `ruff check .`.
  - Package bundle sync check via `python -m finagent.bundler --check`.
  - Unit test suite via `pytest -v`.
  - Gate check: `all-green` job gates merges to `main`.
- **CD / Release Workflow (`.github/workflows/release.yml`)**:
  - Triggers on version tags (e.g. `v0.2.0`).
  - Builds wheel and sdist packages (`python -m build`).
  - Publishes build artifacts to GitHub Releases and PyPI.

---

## 5. Build-in-Public Content Plan & Social Logs

### Post #1: The Origin & Verification Thesis
- **Core Hook**: "Accuracy comes from verification, not extraction."
- **Focus**: Highlighting silent extraction failures in 600-page annual reports and introducing the zero-trust accounting identity thesis.

### Post #2: Stage 1 — Document Profiler Deep Dive (`profiler.py`)
- **Core Hook**: "Why process 600 pages heavy when you only need 6?"
- **Focus**: Explaining the 1-second `pypdf` pre-flight pass, text quality scoring (`OK`, `SUSPECT`, `EMPTY`), and orientation detection.
- **Visual**: Hand-drawn minimalist architecture sketch.

### Upcoming Posts Schedule:
- **Post #3**: Stage 2 — `geometry.py` (Handling A3 Two-Up side-by-side pages).
- **Post #4**: Stage 5 — `normalizer.py` (Stripping Note Ref columns like Note 14).
- **Post #5**: Stage 6 — `validator.py` (The Accounting Identity Verification Engine).
- **Post #6**: CI/CD & Reliability Engineering in Python.
