"""Build and bundle module for finagent_single.py

Generates the single-file distribution finagent_single.py from the modular finagent/ package.
Supports --check flag for CI synchronization verification.
"""
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
PACKAGE_DIR = ROOT / "finagent"
TARGET_FILE = ROOT / "finagent_single.py"

HEADER = '''"""finagent_single.py — the whole Financial PDF Extraction Agent in one file.

This is a portable, single-file build of the `finagent/` package. Same code,
flattened into one module so you can drop it anywhere, paste it in a chat, or
run it without installing a package.

    python finagent_single.py test_pdfs/TCS_2024-2025.pdf

The multi-file package in finagent/ is the source of truth.
AUTO-GENERATED FILE. Do not edit directly; modify finagent/ and run:
    python -m finagent.bundler
"""
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Optional, List, Dict, Tuple

from pypdf import PdfReader
import pdfplumber
from rapidfuzz import fuzz
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill

# Alias modular namespaces to the current module to support the bundled single-file build
profiler = sys.modules[__name__]
locator = sys.modules[__name__]
normalizer = sys.modules[__name__]
unit_detector = sys.modules[__name__]
geometric = sys.modules[__name__]

'''


def clean_imports(content: str) -> str:
    """Strip top-level standard imports, relative imports, and __main__ blocks from module source."""
    lines = content.splitlines()
    out = []
    in_docstring = False
    docstring_quote = None
    in_main = False

    for i, line in enumerate(lines):
        sline = line.strip()
        if i == 0 or (len(out) == 0 and not sline):
            if sline.startswith('"""') or sline.startswith("'''"):
                docstring_quote = sline[:3]
                if sline.count(docstring_quote) >= 2 and len(sline) > 3:
                    continue
                in_docstring = True
                continue
        if in_docstring:
            if docstring_quote in sline:
                in_docstring = False
            continue

        if in_main:
            if not line or line[0].isspace():
                continue
            else:
                in_main = False

        if sline.startswith('if __name__ == "__main__":') or sline.startswith("if __name__ == '__main__':"):
            in_main = True
            continue

        if sline.startswith("from .") or sline.startswith("import ."):
            continue
        if sline in (
            "import re", "import sys", "import time", "from collections import defaultdict",
            "from dataclasses import dataclass, field", "from enum import Enum", "from pathlib import Path",
            "from statistics import median", "from pypdf import PdfReader", "import pdfplumber",
            "from rapidfuzz import fuzz", "from openpyxl import Workbook", "from typing import Optional, List, Dict, Tuple"
        ):
            continue

        out.append(line)

    return "\n".join(out).strip() + "\n\n"


def bundle() -> str:
    """Bundle all finagent modules in topological order."""
    modules = [
        ("SCHEMA", PACKAGE_DIR / "schema.py"),
        ("UNIT DETECTOR", PACKAGE_DIR / "unit_detector.py"),
        ("PROFILER", PACKAGE_DIR / "profiler.py"),
        ("GEOMETRY", PACKAGE_DIR / "geometry.py"),
        ("LOCATOR", PACKAGE_DIR / "locator.py"),
        ("GEOMETRIC EXTRACTOR", PACKAGE_DIR / "extractors" / "geometric.py"),
        ("NORMALIZER", PACKAGE_DIR / "normalizer.py"),
        ("VALIDATOR", PACKAGE_DIR / "validator.py"),
        ("DERIVER", PACKAGE_DIR / "deriver.py"),
        ("WRITER", PACKAGE_DIR / "writer.py"),
        ("PIPELINE", PACKAGE_DIR / "pipeline.py"),
    ]

    parts = [HEADER]
    for section_name, path in modules:
        if not path.exists():
            print(f"Warning: {path} does not exist, skipping.", file=sys.stderr)
            continue
        content = path.read_text(encoding="utf-8")
        cleaned = clean_imports(content)
        parts.append(f"# =============================================================================\n")
        parts.append(f"# {section_name} (from finagent/{path.relative_to(PACKAGE_DIR)})\n")
        parts.append(f"# =============================================================================\n")
        parts.append(cleaned)

    parts.append('''
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python finagent_single.py <pdf_path> [out_excel_path]")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
''')

    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Bundle finagent/ into finagent_single.py")
    parser.add_argument("--check", action="store_true", help="Check if finagent_single.py is up-to-date")
    args = parser.parse_args()

    content = bundle()
    if args.check:
        if not TARGET_FILE.exists():
            print("Error: finagent_single.py does not exist!", file=sys.stderr)
            sys.exit(1)
        existing = TARGET_FILE.read_text(encoding="utf-8")
        if existing.strip() != content.strip():
            print("Error: finagent_single.py is out of sync with finagent/ package!", file=sys.stderr)
            print("Run 'python -m finagent.bundler' to update it.", file=sys.stderr)
            sys.exit(1)
        print("OK: finagent_single.py is up-to-date.")
        sys.exit(0)

    TARGET_FILE.write_text(content, encoding="utf-8")
    print(f"Successfully generated {TARGET_FILE.name}")


if __name__ == "__main__":
    main()
