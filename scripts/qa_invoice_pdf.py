"""Render the SOLA invoice PDF(s) to PNG + dump text for visual/QA.

Usage:
    python scripts/qa_invoice_pdf.py [--all]
Renders _shots/INVOICE_CURRENT.pdf (baseline) and, if present, _shots/INVOICE_NEW.pdf.
"""
import os
import sys

import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "_shots")


def render(path):
    name = os.path.splitext(os.path.basename(path))[0]
    doc = pymupdf.open(path)
    print(f"== {name}: pages={doc.page_count}")
    out = []
    for i, page in enumerate(doc):
        # text dump (should be non-empty; empty => scanned/unreadable layer)
        text = page.get_text("text")
        print(f"  page {i+1}: text_chars={len(text.strip())}")
        # block geometry check: max bottom vs page height - bottom margin (~14mm=40pt)
        H = page.rect.height
        blocks = page.get_text("blocks")
        max_bottom = max((b[3] for b in blocks), default=0)
        print(f"  page {i+1}: height={H:.0f}pt, lowest_text_bottom={max_bottom:.0f}pt, "
              f"overflow_into_bottom_margin={max_bottom > H - 38}")
        pix = page.get_pixmap(dpi=150)
        png = os.path.join(SHOTS, f"{name}_p{i+1}.png")
        pix.save(png)
        print(f"  -> {png}")
        out.append(png)
    return out


if __name__ == "__main__":
    targets = sys.argv[1:] or ["INVOICE_CURRENT.pdf"]
    for t in targets:
        p = os.path.join(SHOTS, t) if not os.path.isabs(t) else t
        if os.path.isfile(p):
            render(p)
        else:
            print(f"skip (not found): {p}")