"""Builds small test documents (digital, scanned, table, image) with PyMuPDF only."""
from typing import List, Optional

import fitz

from app.rag.multimodal import OCRProvider, OCRResult


class FakeOCR(OCRProvider):
    """Returns scripted results in order (or `default`); an Exception in the script is raised."""

    def __init__(self, results: Optional[list] = None, default: Optional[OCRResult] = None):
        self.results = list(results or [])
        self.default = default or OCRResult("Fake OCR text from this region", 0.9, 1)
        self.calls = 0

    def recognize(self, image_png: bytes) -> OCRResult:
        self.calls += 1
        if self.results:
            item = self.results.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return self.default


def render_lines_png(lines: List[str], width: int = 595, height: int = 842, fontsize: int = 22) -> bytes:
    """Text drawn on a blank page, rendered to PNG at 150 dpi (what a scan of it would look like)."""
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    y = 70
    for line in lines:
        page.insert_text((50, y), line, fontsize=fontsize)
        y += fontsize * 2
    png = page.get_pixmap(dpi=150).tobytes("png")
    doc.close()
    return png


def small_png() -> bytes:
    """A 40x40 px image: below the 'real content' size limit (a logo or icon)."""
    doc = fitz.open()
    page = doc.new_page(width=40, height=40)
    page.draw_rect(fitz.Rect(5, 5, 35, 35), fill=(0, 0, 1))
    png = page.get_pixmap(dpi=72).tobytes("png")
    doc.close()
    return png


def make_text_pdf(path: str, pages: List[str]) -> str:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        if text:
            # a wrapped text box, so long text stays on the page and is extracted in full
            page.insert_textbox(fitz.Rect(72, 72, 523, 770), text, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def make_scanned_pdf(path: str, pages: List[List[str]]) -> str:
    """Every page is just an image of text: there is no text layer at all."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        page.insert_image(page.rect, stream=render_lines_png(lines))
    doc.save(path)
    doc.close()
    return path


def make_table_pdf(path: str) -> str:
    """A paragraph, a ruled 4x3 table, and another paragraph."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Quarterly report: the table below lists revenue by region.", fontsize=11)

    left, top, col_w, row_h = 72, 110, 130, 26
    rows = [["Region", "Revenue", "Growth"], ["North", "1200", "12%"], ["South", "950", "8%"], ["East", "1400", "15%"]]
    for r in range(len(rows) + 1):
        page.draw_line((left, top + r * row_h), (left + 3 * col_w, top + r * row_h))
    for c in range(4):
        page.draw_line((left + c * col_w, top), (left + c * col_w, top + len(rows) * row_h))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            page.insert_text((left + c * col_w + 6, top + r * row_h + 17), value, fontsize=10)

    page.insert_text((72, 260), "Revenue grew across all regions this quarter.", fontsize=11)
    doc.save(path)
    doc.close()
    return path


def make_pdf_with_images(path: str, page_texts: List[str], image_lines: List[str], repeat_same_image: bool = False,
                         add_logo: bool = False) -> str:
    """Digital pages, each carrying an embedded picture that contains text (and optionally a tiny logo)."""
    doc = fitz.open()
    png = render_lines_png(image_lines, width=400, height=200, fontsize=18)
    xref = 0
    for index, text in enumerate(page_texts):
        page = doc.new_page()
        page.insert_text((72, 80), text, fontsize=12)
        rect = fitz.Rect(72, 300, 472, 500)
        if repeat_same_image and index > 0:
            page.insert_image(rect, xref=xref)
        else:
            xref = page.insert_image(rect, stream=png)
        if add_logo and index == 0:
            page.insert_image(fitz.Rect(500, 20, 540, 60), stream=small_png())
    doc.save(path)
    doc.close()
    return path


def make_png_file(path: str, lines: List[str]) -> str:
    with open(path, "wb") as handle:
        handle.write(render_lines_png(lines))
    return path