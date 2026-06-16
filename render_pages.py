"""Render PDF pages to PNG for visual golden-dataset reading.

    python render_pages.py <pdf> <1-based pages: 180,181,184-185> [scale]
"""
import sys
from pathlib import Path

import pypdfium2 as pdfium


def parse_pages(spec):
    out = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def main():
    pdf_path, spec = Path(sys.argv[1]), sys.argv[2]
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
    out_dir = Path("output") / "golden_pages"
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf_path))
    for p in parse_pages(spec):
        img = doc[p - 1].render(scale=scale).to_pil()
        out = out_dir / f"{pdf_path.stem}_p{p}.png"
        img.save(out)
        print(out)


if __name__ == "__main__":
    main()
