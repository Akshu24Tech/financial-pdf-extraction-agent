"""
Benchmark script to compare Docling vs pdfplumber for financial PDF extraction.

This script compares:
1. Table structure preservation
2. Heading preservation
3. Reading order accuracy

on Airtel, TCS, and Newgen PDFs.
"""

import json
import os
import re

# Add the project root to Python path to import finagent modules
import sys
from pathlib import Path
from typing import Any

from docling.document_converter import DocumentConverter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))

from finagent.extractors.geometric import extract as pdfplumber_extract


def extract_with_pdfplumber(
    pdf_path: str, page_indices: list[int] | None = None
) -> list[dict[str, Any]]:
    """
    Extract tables using the current pdfplumber approach.
    Returns list of RawItem objects.
    """
    if page_indices is None:
        page_indices = [0]  # Default to first page for benchmark

    raw_items = pdfplumber_extract(pdf_path, page_indices)

    # Convert to benchmark format
    return [
        {"label": item.label, "values": item.values, "page": item.page, "source": "pdfplumber"}
        for item in raw_items
    ]


def extract_with_docling(pdf_path: str) -> list[dict[str, Any]]:
    """
    Extract tables using Docling.
    Returns list of extracted items in the same format as pdfplumber.
    """
    converter = DocumentConverter()
    doc = converter.convert(pdf_path)

    extracted_items = []

    # Process tables from Docling output
    for table in doc.tables:
        for row_idx, row in enumerate(table.rows):
            # First row is typically headers
            if row_idx == 0:
                continue

            # Try to reconstruct label and values
            label = ""
            values = []

            for cell_idx, cell in enumerate(row.cells):
                cell_text = cell.text.strip()

                # First cell is typically the label
                if cell_idx == 0:
                    label = cell_text
                else:
                    # Subsequent cells are values
                    if cell_text and not cell_text.isspace():
                        values.append(cell_text)

            if label:  # Only add if we have a label
                extracted_items.append(
                    {
                        "label": label,
                        "values": values,
                        "page": table.metadata.page_number
                        if hasattr(table.metadata, "page_number")
                        else 0,
                        "source": "docling",
                    }
                )

    # Process text blocks for headings and other content
    for block in doc.content:
        if block.type == "text" and block.text.strip():
            # Check if this looks like a heading
            text = block.text.strip()
            if is_heading(text):
                extracted_items.append(
                    {
                        "label": text,
                        "values": [],
                        "page": block.metadata.page_number
                        if hasattr(block.metadata, "page_number")
                        else 0,
                        "source": "docling_heading",
                    }
                )

    return extracted_items


def is_heading(text: str) -> bool:
    """Check if text looks like a heading."""
    # Simple heuristic: short text, title case, no numbers
    return len(text.split()) <= 5 and text == text.title() and not re.search(r"\d", text)


def compare_extractions(pdfplumber_items: list[dict], docling_items: list[dict]) -> dict[str, Any]:
    """
    Compare the two extraction approaches.
    Returns comparison metrics.
    """
    metrics = {
        "table_rows": {"pdfplumber": 0, "docling": 0, "matching": 0},
        "headings": {"pdfplumber": 0, "docling": 0, "matching": 0},
        "value_accuracy": 0.0,
        "label_accuracy": 0.0,
    }

    # Count table rows
    pdfplumber_rows = [item for item in pdfplumber_items if item["values"]]
    docling_rows = [item for item in docling_items if item["values"]]

    metrics["table_rows"]["pdfplumber"] = len(pdfplumber_rows)
    metrics["table_rows"]["docling"] = len(docling_rows)

    # Count matching rows (simple string matching for benchmark)
    for p_row in pdfplumber_rows:
        for d_row in docling_rows:
            if p_row["label"].strip().lower() == d_row["label"].strip().lower():
                # Check if values match
                p_values = [str(v).strip().lower() for v in p_row["values"]]
                d_values = [str(v).strip().lower() for v in d_row["values"]]

                if p_values == d_values:
                    metrics["table_rows"]["matching"] += 1
                    break

    # Count headings
    pdfplumber_headings = [item for item in pdfplumber_items if not item["values"]]
    docling_headings = [
        item for item in docling_items if not item["values"] and item["source"] == "docling_heading"
    ]

    metrics["headings"]["pdfplumber"] = len(pdfplumber_headings)
    metrics["headings"]["docling"] = len(docling_headings)

    # Count matching headings
    for p_heading in pdfplumber_headings:
        for d_heading in docling_headings:
            if p_heading["label"].strip().lower() == d_heading["label"].strip().lower():
                metrics["headings"]["matching"] += 1
                break

    # Calculate accuracy scores
    total_rows = max(metrics["table_rows"]["pdfplumber"], metrics["table_rows"]["docling"])
    if total_rows > 0:
        metrics["value_accuracy"] = metrics["table_rows"]["matching"] / total_rows

    total_headings = max(metrics["headings"]["pdfplumber"], metrics["headings"]["docling"])
    if total_headings > 0:
        metrics["label_accuracy"] = metrics["headings"]["matching"] / total_headings

    return metrics


def benchmark_pdf(pdf_path: str) -> dict[str, Any]:
    """Run benchmark on a single PDF."""
    print(f"Benchmarking {Path(pdf_path).name}...")

    # Extract with both approaches
    pdfplumber_items = extract_with_pdfplumber(pdf_path)
    docling_items = extract_with_docling(pdf_path)

    # Compare
    comparison = compare_extractions(pdfplumber_items, docling_items)

    return {
        "pdf": Path(pdf_path).name,
        "pdfplumber": {
            "table_rows": len([item for item in pdfplumber_items if item["values"]]),
            "headings": len([item for item in pdfplumber_items if not item["values"]]),
        },
        "docling": {
            "table_rows": len([item for item in docling_items if item["values"]]),
            "headings": len([item for item in docling_items if not item["values"]]),
        },
        "comparison": comparison,
    }


def main():
    """Run benchmark on Airtel, TCS, and Newgen PDFs."""
    test_pdfs_dir = Path("test_pdfs")

    # PDFs to benchmark
    pdf_files = [
        test_pdfs_dir / "Airtel_2024-25.pdf",
        test_pdfs_dir / "TCS_2024-2025.pdf",
        test_pdfs_dir / "Newgen.pdf",
    ]

    results = []

    for pdf_file in pdf_files:
        if pdf_file.exists():
            result = benchmark_pdf(str(pdf_file))
            results.append(result)
        else:
            print(f"PDF not found: {pdf_file}")

    # Print and save results
    print("\n=== Benchmark Results ===")
    for result in results:
        print(f"\nPDF: {result['pdf']}")
        print(
            f"pdfplumber: {result['pdfplumber']['table_rows']} table rows, {result['pdfplumber']['headings']} headings"
        )
        print(
            f"docling: {result['docling']['table_rows']} table rows, {result['docling']['headings']} headings"
        )
        print(
            f"Matching table rows: {result['comparison']['table_rows']['matching']} ({result['comparison']['value_accuracy']:.1%})"
        )
        print(
            f"Matching headings: {result['comparison']['headings']['matching']} ({result['comparison']['label_accuracy']:.1%})"
        )

    # Save results to JSON
    with open("benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults saved to benchmark_results.json")


if __name__ == "__main__":
    main()
