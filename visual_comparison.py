"""
Minimal visual comparison of Docling vs pdfplumber output.

This script extracts the first page from each PDF and shows sample output
from both approaches for qualitative comparison.
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any

# Try to import both libraries
try:
    from docling.document_converter import DocumentConverter
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False
    print("Docling not available - will only show pdfplumber output")

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    print("pdfplumber not available - will only show Docling output")


def extract_with_pdfplumber(pdf_path: str, page_num: int = 0) -> List[Dict[str, Any]]:
    """Extract text and tables using pdfplumber."""
    extracted_items = []

    with pdfplumber.open(pdf_path) as pdf:
        if page_num < len(pdf.pages):
            page = pdf.pages[page_num]
            text = page.extract_text()

            if text:
                lines = text.split('\n')
                for line in lines:
                    line = line.strip()
                    if line:
                        # Simple heuristic for table rows
                        if re.search(r'\d', line) and len(line.split()) > 3:
                            parts = re.split(r'\s{2,}', line)
                            if len(parts) >= 2:
                                extracted_items.append({
                                    "type": "table_row",
                                    "content": line,
                                    "label": parts[0].strip(),
                                    "values": [p.strip() for p in parts[1:] if p.strip()]
                                })
                        else:
                            extracted_items.append({
                                "type": "text",
                                "content": line
                            })

            # Extract tables
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and any(cell.strip() for cell in row if cell):
                        label = row[0].strip() if row[0] else ""
                        values = [cell.strip() for cell in row[1:] if cell and cell.strip()]
                        if label:
                            extracted_items.append({
                                "type": "table",
                                "content": " | ".join([label] + values),
                                "label": label,
                                "values": values
                            })

    return extracted_items


def extract_with_docling(pdf_path: str) -> List[Dict[str, Any]]:
    """Extract content using Docling."""
    converter = DocumentConverter()
    doc = converter.convert(pdf_path)

    extracted_items = []

    # Process tables
    for table in doc.tables:
        for row in table.rows:
            if not row.cells:
                continue

            label = ""
            values = []

            for cell_idx, cell in enumerate(row.cells):
                cell_text = cell.text.strip() if cell.text else ""

                if cell_idx == 0:
                    label = cell_text
                else:
                    if cell_text:
                        values.append(cell_text)

            if label:
                extracted_items.append({
                    "type": "table",
                    "content": " | ".join([label] + values),
                    "label": label,
                    "values": values
                })

    # Process text blocks
    for block in doc.content:
        if block.type == "text" and block.text and block.text.strip():
            text = block.text.strip()
            extracted_items.append({
                "type": "text",
                "content": text
            })

    return extracted_items


def main():
    """Run visual comparison on Airtel, TCS, and Newgen PDFs."""
    test_pdfs_dir = Path("test_pdfs")

    # PDFs to compare
    pdf_files = [
        test_pdfs_dir / "Airtel_2024-25.pdf",
        test_pdfs_dir / "TCS_2024-2025.pdf",
        test_pdfs_dir / "Newgen.pdf"
    ]

    for pdf_file in pdf_files:
        if not pdf_file.exists():
            print(f"PDF not found: {pdf_file}")
            continue

        print(f"\n{'='*60}")
        print(f"PDF: {pdf_file.name}")
        print(f"{'='*60}")

        # Extract with pdfplumber if available
        if PDFPLUMBER_AVAILABLE:
            print("\n--- pdfplumber output ---")
            try:
                pdfplumber_items = extract_with_pdfplumber(str(pdf_file), 0)
                table_rows = [item for item in pdfplumber_items if item["type"] in ["table_row", "table"]]
                text_items = [item for item in pdfplumber_items if item["type"] == "text"]

                print(f"Found {len(table_rows)} table rows, {len(text_items)} text items")

                # Show sample table rows
                print("\nSample table rows:")
                for item in table_rows[:5]:
                    print(f"  {item['content']}")

                # Show sample text
                print("\nSample text:")
                for item in text_items[:3]:
                    print(f"  {item['content']}")

            except Exception as e:
                print(f"Error with pdfplumber: {e}")

        # Extract with Docling if available
        if DOCLING_AVAILABLE:
            print("\n--- Docling output ---")
            try:
                docling_items = extract_with_docling(str(pdf_file))
                table_rows = [item for item in docling_items if item["type"] == "table"]
                text_items = [item for item in docling_items if item["type"] == "text"]

                print(f"Found {len(table_rows)} table rows, {len(text_items)} text items")

                # Show sample table rows
                print("\nSample table rows:")
                for item in table_rows[:5]:
                    print(f"  {item['content']}")

                # Show sample text
                print("\nSample text:")
                for item in text_items[:3]:
                    print(f"  {item['content']}")

            except Exception as e:
                print(f"Error with Docling: {e}")


if __name__ == "__main__":
    main()