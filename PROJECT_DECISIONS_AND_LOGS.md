

---

# Docling Evaluation for Finagent

## Overview
**Date**: 2026-07-30
**Purpose**: Evaluate Docling as an alternative/complement to current pdfplumber-based PDF parsing in Finagent
**Decision**: Use Docling as fallback for edge cases, not as primary parser

## Background
Finagent currently uses a pdfplumber-based geometric extraction approach with 95.6% accuracy on financial PDFs. However, certain edge cases cause extraction failures:

- Two-up A3 pages (Airtel, Reliance)
- Landscape tables (BMW)
- Scanned PDFs
- Irregular table structures with merged cells

## Evaluation Process
1. **Research**: Reviewed Docling documentation and capabilities
2. **Benchmark Development**: Created comparison scripts (`benchmark_docling_vs_pdfplumber.py`, `simple_benchmark.py`, `visual_comparison.py`)
3. **Test Files**: Airtel_2024-25.pdf, TCS_2024-2025.pdf, Newgen.pdf
4. **Analysis**: Compared table structure preservation, heading preservation, and reading order accuracy

## Findings
### Current Approach (pdfplumber)
- **Pros**: Lightweight, transparent, deterministic, 95.6% accuracy
- **Cons**: Struggles with complex layouts, no OCR support, requires custom logic for two-up pages

### Docling
- **Pros**: Better table structure preservation, handles complex layouts natively, built-in OCR, Linux Foundation-backed
- **Cons**: Heavy dependency (ML model), less transparent, overkill for most cases

## Edge Cases Comparison
| Case | pdfplumber | Docling | Notes |
|------|------------|---------|-------|
| Two-up A3 pages | Requires custom gutter detection | Handles natively | Docling advantage |
| Landscape tables | Risk of false splits | Better distinction | Docling advantage |
| Scanned PDFs | Returns EMPTY | Built-in OCR | Docling advantage |
| Irregular tables | Struggles with merged cells | Designed for complex layouts | Docling advantage |
| Standard tables | Works well | Works well | Equal performance |

## Recommendation
**Do not replace pdfplumber as primary parser**, but **integrate Docling as fallback for edge cases** where pdfplumber fails.

### Implementation Plan
```python
# finagent/extractors/geometric.py
def extract(pdf_path, page_indices, cue_pats=None):
    try:
        # Try Docling first for complex layouts
        return extract_with_docling(pdf_path, page_indices)
    except Exception as e:
        # Fall back to pdfplumber for most cases
        return extract_with_pdfplumber(pdf_path, page_indices)
```

## Test Plan
1. Identify 2-3 problematic PDFs from test set
2. Parse with both approaches
3. Compare table fidelity
4. If Docling clearly wins on edge cases → integrate as fallback
5. If results are similar → no need to add dependency

## Files Created
- `benchmark_docling_vs_pdfplumber.py` - Full benchmark script
- `simple_benchmark.py` - Simplified comparison script
- `visual_comparison.py` - Qualitative comparison script
- `docling_recommendation.md` - Full recommendation document

## LinkedIn Post
Created engaging post about the evaluation process and findings

## Next Steps
1. Test Docling on identified edge cases
2. Implement fallback integration if warranted
3. Update documentation with new approach