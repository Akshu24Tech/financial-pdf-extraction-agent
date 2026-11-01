# Docling vs pdfplumber: Recommendation for Finagent

## Executive Summary
**Recommendation**: Do not replace `pdfplumber` with Docling as your primary parser, but **test Docling as a fallback for edge cases** where your current approach struggles with complex table layouts.

## Why This Recommendation?

### 1. Your Current Approach Already Works Well
- **95.6% accuracy** on diverse financial PDFs (TCS, Reliance, BMW, etc.)
- **Deterministic validation** catches errors (e.g., wrong numbers breaking accounting identities)
- **Lightweight and transparent** (no ML models, easy to debug)

### 2. Docling's Strengths (Where It Could Help)
- **Complex table layouts**: Better at preserving structure in irregular tables (merged cells, multi-column layouts)
- **Scanned PDFs**: Built-in OCR handles scanned documents (currently marked as `EMPTY` in your profiler)
- **Reading order**: Better at maintaining correct reading order in multi-column documents

### 3. Docling's Weaknesses (Why Not Primary)
- **Heavy dependency**: Adds ML model overhead (compute cost, memory usage)
- **Black-box parsing**: Less transparent than your coordinate-based approach
- **Overkill for most cases**: Your current approach handles 95% of PDFs well

## Specific Edge Cases Where Docling Would Help
Based on your project logs and code, these are the scenarios where Docling would improve accuracy:

1. **Airtel's two-up A3 pages**
   - Current: Requires custom gutter detection logic in `geometry.py`
   - Docling: Handles natively with layout model

2. **BMW's landscape balance sheets**
   - Current: Risk of false splits on wide numerical tables
   - Docling: Better at distinguishing wide tables from two-up pages

3. **Scanned PDFs**
   - Current: Returns `EMPTY` (no OCR support)
   - Docling: Built-in OCR + layout pipeline

4. **Irregular table structures**
   - Current: Struggles with merged cells, irregular spacing
   - Docling: Designed specifically for complex layouts

## Recommended Implementation
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

## Quick Test Plan
1. **Identify 2-3 problematic PDFs** from your test set (where `pdfplumber` misaligns rows/columns)
2. **Parse them with Docling** to see if it fixes the table structure
3. **If Docling clearly wins** on these edge cases → integrate as fallback
4. **If results are similar** → no need to add the dependency

## Bottom Line
Your current stack is **production-ready and deterministic**. Docling is worth testing **only for the edge cases** where `pdfplumber` struggles. The validator's error-catching makes the extraction layer less critical - focus on fixing the root cause (table extraction quality) rather than chasing marginal gains.