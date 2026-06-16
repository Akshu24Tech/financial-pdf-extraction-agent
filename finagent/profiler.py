"""Stage 1: document profile — what kind of PDF is this, page by page?

Uses pypdf (fast) for the full-document pass. pdfplumber is reserved for
the few pages we actually extract from.
"""
import re
from dataclasses import dataclass, field

from pypdf import PdfReader


@dataclass
class PageProfile:
    index: int                # 0-based
    width: float
    height: float
    landscape: bool
    text: str                 # raw extracted text (kept for the locator)
    text_quality: str         # OK / SUSPECT / EMPTY


@dataclass
class DocProfile:
    path: str
    n_pages: int
    pages: list = field(default_factory=list)

    @property
    def landscape_ratio(self):
        return sum(p.landscape for p in self.pages) / max(self.n_pages, 1)

    def summary(self):
        q = {}
        for p in self.pages:
            q[p.text_quality] = q.get(p.text_quality, 0) + 1
        return {"pages": self.n_pages, "landscape_ratio": round(self.landscape_ratio, 2),
                "text_quality": q}


def _quality(text):
    if not text or len(text.strip()) < 50:
        return "EMPTY"
    alpha = sum(len(w) for w in re.findall(r"[A-Za-z]{3,}", text))
    return "OK" if alpha / max(len(text), 1) > 0.3 else "SUSPECT"


def profile(pdf_path):
    reader = PdfReader(pdf_path)
    doc = DocProfile(path=str(pdf_path), n_pages=len(reader.pages))
    for i, page in enumerate(reader.pages):
        box = page.mediabox
        w, h = float(box.width), float(box.height)
        rotation = page.get("/Rotate") or 0
        if rotation in (90, 270):
            w, h = h, w
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        doc.pages.append(PageProfile(
            index=i, width=w, height=h, landscape=w > h,
            text=text, text_quality=_quality(text),
        ))
    return doc
