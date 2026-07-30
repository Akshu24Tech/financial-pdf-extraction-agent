"""
Simple benchmark script to compare Docling vs pdfplumber for financial PDF extraction.

This script compares the raw output from both approaches on Airtel, TCS, and Newgen PDFs.
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any

import pdfplumber
from docling.document_converter import DocumentConverter


def extract_with_pdfplumber(pdf_path: str, page_num: int = 0) -> List[Dict[str, Any]]:
    """
    Extract text and tables using pdfplumber.
    """
    extracted_items = []

    with pdfplumber.open(pdf_path) as pdf:
        if page_num < len(pdf.pages):
            page = pdf.pages[page_num]

            # Extract text
            text = page.extract_text()
            if text:
                # Split into lines and look for potential table rows
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if line:
                        # Simple heuristic: if line contains numbers, it might be a table row
                        if re.search(r'\d', line):
                            # Split into label and values
                            parts = re.split(r'\s{2,}', line)  # Split on 2+ spaces
                            if len(parts) >= 2:
                                label = parts[0].strip()
                                values = [p.strip() for p in parts[1:] if p.strip()]
                                extracted_items.append({
                                    "label": label,
                                    "values": values,
                                    "page": page_num + 1,
                                    "source": "pdfplumber_table"
                                })
                            else:
                                extracted_items.append({
                                    "label": line,
                                    "values": [],
                                    "page": page_num + 1,
                                    "source": "pdfplumber_text"
                                })
                        else:
                            # Potential heading
                            extracted_items.append({
                                "label": line,
                                "values": [],
                                "page": page_num + 1,
                                "source": "pdfplumber_heading"
                            })

            # Extract tables
            tables = page.extract_tables()
            for table in tables:
                for row_idx, row in enumerate(table):
                    if row and any(cell.strip() for cell in row if cell):
                        label = row[0].strip() if row[0] else ""
                        values = [cell.strip() for cell in row[1:] if cell and cell.strip()]
                        if label:
                            extracted_items.append({
                                "label": label,
                                "values": values,
                                "page": page_num + 1,
                                "source": "pdfplumber_table"
                            })

    return extracted_items


def extract_with_docling(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract content using Docling.
    """
    converter = DocumentConverter()
    doc = converter.convert(pdf_path)

    extracted_items = []

    # Process tables
    for table in doc.tables:
        for row_idx, row in enumerate(table.rows):
            # Skip empty rows
            if not row.cells:
                continue

            # Try to reconstruct label and values
            label = ""
            values = []

            for cell_idx, cell in enumerate(row.cells):
                cell_text = cell.text.strip() if cell.text else ""

                # First cell is typically the label
                if cell_idx == 0:
                    label = cell_text
                else:
                    # Subsequent cells are values
                    if cell_text:
                        values.append(cell_text)

            if label:  # Only add if we have a label
                extracted_items.append({
                    "label": label,
                    "values": values,
                    "page": table.metadata.page_number if hasattr(table.metadata, 'page_number') else 0,
                    "source": "docling_table"
                })

    # Process text blocks for headings and other content
    for block in doc.content:
        if block.type == "text" and block.text and block.text.strip():
            text = block.text.strip()
            # Check if this looks like a heading
            if is_heading(text):
                extracted_items.append({
                    "label": text,
                    "values": [],
                    "page": block.metadata.page_number if hasattr(block.metadata, 'page_number') else 0,
                    "source": "docling_heading"
                })
            elif re.search(r'\d', text):  # Contains numbers - potential table row
                extracted_items.append({
                    "label": text,
                    "values": [],
                    "page": block.metadata.page_number if hasattr(block.metadata, 'page_number') else 0,
                    "source": "docling_text"
                })

    return extracted_items


def is_heading(text: str) -> bool:
    """Check if text looks like a heading."""
    # Simple heuristic: short text, title case, no numbers
    if len(text.split()) <= 5 and text == text.title() and not re.search(r'\d', text):
        return True
    return False


def compare_extractions(pdfplumber_items: List[Dict], docling_items: List[Dict]) -> Dict[str, Any]:
    """
    Compare the two extraction approaches.
    """
    metrics = {
        "table_rows": {
            "pdfplumber": 0,
            "docling": 0,
            "matching": 0
        },
        "headings": {
            "pdfplumber": 0,
            "docling": 0,
            "matching": 0
        },
        "value_accuracy": 0.0,
        "label_accuracy": 0.0
    }

    # Count table rows
    pdfplumber_rows = [item for item in pdfplumber_items if item["source"].endswith("_table")]
    docling_rows = [item for item in docling_items if item["source"].endswith("_table")]

    metrics["table_rows"]["pdfplumber"] = len(pdfplumber_rows)
    metrics["table_rows"]["docling"] = len(docling_rows)

    # Count matching rows (simple string matching)
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
    pdfplumber_headings = [item for item in pdfplumber_items if item["source"] == "pdfplumber_heading"]
    docling_headings = [item for item in docling_items if item["source"] == "docling_heading"]

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


def benchmark_pdf(pdf_path: str) -> Dict[str, Any]:
    """Run benchmark on a single PDF."""
    print(f"Benchmarking {Path(pdf_path).name}...")

    # Extract with both approaches (first page only for quick comparison)
    pdfplumber_items = extract_with_pdfplumber(pdf_path, 0)
    docling_items = extract_with_docling(pdf_path)

    # Compare
    comparison = compare_extractions(pdfplumber_items, docling_items)

    return {
        "pdf": Path(pdf_path).name,
        "pdfplumber": {
            "table_rows": len([item for item in pdfplumber_items if item["source"].endswith("_table")]),
            "headings": len([item for item in pdfplumber_items if item["source"] == "pdfplumber_heading"]),
            "text_items": len([item for item in pdfplumber_items if item["source"] == "pdfplumber_text"])
        },
        "docling": {
            "table_rows": len([item for item in docling_items if item["source"].endswith("_table")]),
            "headings": len([item for item in docling_items if item["source"] == "docling_heading"]),
            "text_items": len([item for item in docling_items if item["source"] == "docling_text"])
        },
        "comparison": comparison
    }


def main():
    """Run benchmark on Airtel, TCS, and Newgen PDFs."""
    test_pdfs_dir = Path("test_pdfs")

    # PDFs to benchmark
    pdf_files = [
        test_pdfs_dir / "Airtel_2024-25.pdf",
        test_pdfs_dir / "TCS_2024-2025.pdf",
        test_pdfs_dir / "Newgen.pdf"
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
        print(f"pdfplumber: {result['pdfplumber']['table_rows']} table rows, {result['pdfplumber']['headings']} headings")
        print(f"docling: {result['docling']['table_rows']} table rows, {result['docling']['headings']} headings")
        print(f"Matching table rows: {result['comparison']['table_rows']['matching']} ({result['comparison']['value_accuracy']:.1%})")
        print(f"Matching headings: {result['comparison']['headings']['matching']} ({result['comparison']['label_accuracy']:.1%})")

    # Save results to JSON
    with open("benchmark_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults saved to benchmark_results.json")

    # Print sample output for qualitative comparison
    print("\n=== Sample Output Comparison ===")
    for result in results:
        print(f"\nPDF: {result['pdf']}")
        print("\npdfplumber sample output:")
        for item in [i for i in extract_with_pdfplumber(str(test_pdfs_dir / result['pdf']), 0) if i['source'].endswith('_table')][:3]:
            print(f"  {item['label']}: {item['values']}")

        print("\nDocling sample output:")
        for item in [i for i in extract_with_docling(str(test_pdfs_dir / result['pdf'])) if i['source'].endswith('_table')][:3]:
            print(f"  {item['label']}: {item['values']}")


if __name__ == "__main__":
    main()