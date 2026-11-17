"""
Multimodal ingestion (Phase 10): turns an uploaded file into typed ELEMENTS.

    text        digital text (PDF page text, .txt files)           -> chunked like before
    table       a table found in a PDF, kept as a Markdown table    -> chunked by rows
    ocr         a scanned PDF page or an image file, read by OCR    -> chunked like text
    image_text  text found inside an image embedded in a PDF page   -> chunked like text

Digital pages WITHOUT tables go through exactly the same call as before
(page.get_text()), so documents that worked before are chunked identically.
Everything slow or heavy is bounded (OCR page/image caps, pixel limits) and everything
that was skipped is reported, never silently dropped.

Not implemented: image EMBEDDINGS (e.g. CLIP). A photo or chart with no readable text
is therefore not searchable; only the text inside images is.
"""
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional, Set, Tuple

import fitz  # PyMuPDF

from app.core.config import settings

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = ("png", "jpg", "jpeg")

MAX_IMAGE_PIXELS = 25_000_000          # refuse to decode anything bigger (decompression bombs)
MIN_EMBEDDED_IMAGE_SIDE = 150          # smaller images are icons/logos, not content
MIN_IMAGE_TEXT_CHARS = 15              # OCR output shorter than this from an embedded image is noise
MIN_PAGE_TEXT_CHARS = 20               # a page with less text than this ...
MIN_SCAN_COVERAGE = 0.5                # ... AND images covering this share of the page is a scan
MAX_TABLE_CHARS = 2000
MIN_TABLE_ROWS = 2
MIN_TABLE_COLS = 2


@dataclass
class Element:
    page_number: Optional[int]
    kind: str                          # "text" | "table" | "ocr" | "image_text"
    text: str
    confidence: Optional[float] = None


@dataclass
class OCRResult:
    text: str
    confidence: float                  # mean confidence of the kept lines; 0 when nothing was read
    lines: int


@dataclass
class IngestReport:
    source: str = "text"               # "text" | "pdf" | "image"
    pages_total: Optional[int] = None
    pages_text: int = 0
    pages_ocr: int = 0
    tables: int = 0
    images_ocr: int = 0
    images_skipped: int = 0
    ocr_available: bool = False
    ocr_pages_unavailable: int = 0
    ocr_pages_skipped_limit: int = 0
    ocr_images_skipped_limit: int = 0
    ocr_errors: int = 0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------------ OCR

class OCRProvider(ABC):
    @abstractmethod
    def recognize(self, image_png: bytes) -> OCRResult:
        ...


def assemble_ocr_result(lines: List[Tuple[str, float]], min_confidence: float) -> OCRResult:
    """Keeps lines with text and confidence >= min_confidence; reports their mean confidence."""
    kept = [
        (text.strip(), float(score))
        for text, score in lines
        if text and text.strip() and float(score) >= min_confidence
    ]
    if not kept:
        return OCRResult(text="", confidence=0.0, lines=0)
    return OCRResult(
        text="\n".join(text for text, _ in kept),
        confidence=sum(score for _, score in kept) / len(kept),
        lines=len(kept),
    )


class RapidOCRProvider(OCRProvider):
    """RapidOCR (ONNX runtime, CPU). pip-installable; the models ship inside the package."""

    _engine = None  # loaded on first use and shared (loading takes several seconds)

    def __init__(self, min_confidence: float):
        self.min_confidence = min_confidence

    @classmethod
    def _get_engine(cls):
        if cls._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            cls._engine = RapidOCR()
        return cls._engine

    def recognize(self, image_png: bytes) -> OCRResult:
        import io

        import numpy as np
        from PIL import Image

        image = Image.open(io.BytesIO(image_png)).convert("RGB")
        result, _ = self._get_engine()(np.array(image))
        lines = [(text, score) for _box, text, score in (result or [])]
        return assemble_ocr_result(lines, self.min_confidence)


def get_ocr_provider() -> Optional[OCRProvider]:
    """The OCR engine, or None when OCR is switched off or the package isn't installed."""
    if not settings.OCR_ENABLED:
        return None
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        logger.warning("rapidocr-onnxruntime is not installed; scanned pages and images will not be read")
        return None
    return RapidOCRProvider(settings.OCR_MIN_CONFIDENCE)


# --------------------------------------------------------------------- tables

def _clean_cell(value: Any) -> str:
    text = " ".join(str(value).split()) if value is not None else ""
    return text.replace("|", "/")


def table_to_markdown(rows: List[List[Any]]) -> str:
    """Rows of cells -> a Markdown table. Returns '' if what remains isn't a real table."""
    cleaned = [[_clean_cell(cell) for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(row)]
    if not cleaned:
        return ""

    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    keep = [i for i in range(width) if any(row[i] for row in cleaned)]
    cleaned = [[row[i] for i in keep] for row in cleaned]

    if len(cleaned) < MIN_TABLE_ROWS or len(cleaned[0]) < MIN_TABLE_COLS:
        return ""

    header, body = cleaned[0], cleaned[1:]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)


def chunk_table(markdown: str, max_chars: int = MAX_TABLE_CHARS) -> List[str]:
    """
    A table stays in one chunk when it fits. A longer one is split by rows, and EVERY
    piece repeats the header so a chunk still says what its columns mean.
    """
    if len(markdown) <= max_chars:
        return [markdown]

    lines = markdown.split("\n")
    header, body = "\n".join(lines[:2]), lines[2:]
    budget = max(max_chars - len(header) - 1, 50)

    chunks: List[str] = []
    current: List[str] = []
    size = 0
    for row in body:
        if len(row) > budget:
            row = row[: budget - 1] + "…"
        if current and size + len(row) + 1 > budget:
            chunks.append(header + "\n" + "\n".join(current))
            current, size = [], 0
        current.append(row)
        size += len(row) + 1
    if current:
        chunks.append(header + "\n" + "\n".join(current))
    return chunks or [markdown]


# ------------------------------------------------------------------ pdf pages

def _overlap_ratio(block: "fitz.Rect", table: "fitz.Rect") -> float:
    area = block.get_area()
    if area <= 0:
        return 0.0
    intersection = block & table
    if intersection.is_empty:
        return 0.0
    return intersection.get_area() / area


def _text_outside_tables(page: "fitz.Page", table_rects: List["fitz.Rect"]) -> str:
    parts = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, _number, block_type = block[:7]
        if block_type != 0:
            continue
        rect = fitz.Rect(x0, y0, x1, y1)
        if any(_overlap_ratio(rect, table_rect) > 0.5 for table_rect in table_rects):
            continue
        cleaned = text.strip()
        if cleaned:
            parts.append(cleaned)
    return "\n".join(parts)


def _find_tables(page: "fitz.Page") -> List[Tuple["fitz.Rect", str]]:
    if not settings.TABLES_ENABLED:
        return []
    try:
        finder = page.find_tables()
    except Exception as exc:
        logger.warning("Table detection failed on a page: %s", exc)
        return []

    found = []
    for table in getattr(finder, "tables", []):
        try:
            markdown = table_to_markdown(table.extract())
        except Exception:
            continue
        if markdown:
            found.append((fitz.Rect(table.bbox), markdown))
    return found


def _render_page_png(page: "fitz.Page", dpi: int) -> bytes:
    width_px = page.rect.width / 72 * dpi
    height_px = page.rect.height / 72 * dpi
    if width_px * height_px > MAX_IMAGE_PIXELS:           # a huge page: lower the resolution to fit
        dpi = max(72, int(dpi * math.sqrt(MAX_IMAGE_PIXELS / (width_px * height_px))))
    return page.get_pixmap(dpi=dpi).tobytes("png")


def _embedded_image_png(doc: "fitz.Document", xref: int) -> Optional[bytes]:
    try:
        pix = fitz.Pixmap(doc, xref)
        if pix.width < MIN_EMBEDDED_IMAGE_SIDE or pix.height < MIN_EMBEDDED_IMAGE_SIDE:
            return None
        if pix.width * pix.height > MAX_IMAGE_PIXELS:
            return None
        if pix.colorspace is None or pix.colorspace.n != 3 or pix.alpha:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        return pix.tobytes("png")
    except Exception:
        return None


def _image_coverage(page: "fitz.Page", image_refs: list) -> float:
    """Share of the page area covered by images (0-1). A scanned page is one big picture."""
    page_area = page.rect.get_area()
    if page_area <= 0:
        return 0.0
    covered = 0.0
    for image in image_refs:
        try:
            covered += sum(rect.get_area() for rect in page.get_image_rects(image[0]))
        except Exception:
            continue
    return min(covered / page_area, 1.0)


def _recognize(ocr: OCRProvider, png: bytes, report: IngestReport) -> Optional[OCRResult]:
    try:
        return ocr.recognize(png)
    except Exception as exc:
        report.ocr_errors += 1
        logger.warning("OCR failed on one region: %s", exc)
        return None


def extract_pdf_elements(file_path: str, ocr: Optional[OCRProvider], report: IngestReport) -> List[Element]:
    elements: List[Element] = []
    seen_images: Set[int] = set()
    ocr_pages = ocr_images = 0

    with fitz.open(file_path) as doc:
        report.pages_total = len(doc)

        for page_number, page in enumerate(doc, start=1):
            tables = _find_tables(page)
            if tables:
                text = _text_outside_tables(page, [rect for rect, _ in tables])
            else:
                text = page.get_text().strip()          # identical to the pre-Phase-10 behavior

            image_refs = page.get_images(full=True)
            is_scanned = (
                len("".join(text.split())) < MIN_PAGE_TEXT_CHARS
                and not tables
                and bool(image_refs)
                and _image_coverage(page, image_refs) >= MIN_SCAN_COVERAGE
            )

            page_was_ocrd = False
            if is_scanned:
                if ocr is None:
                    report.ocr_pages_unavailable += 1
                elif ocr_pages >= settings.OCR_MAX_PAGES:
                    report.ocr_pages_skipped_limit += 1
                else:
                    ocr_pages += 1
                    result = _recognize(ocr, _render_page_png(page, settings.OCR_RENDER_DPI), report)
                    if result and result.text.strip():
                        elements.append(Element(page_number, "ocr", result.text, result.confidence))
                        report.pages_ocr += 1
                        page_was_ocrd = True

            if text and not page_was_ocrd:
                elements.append(Element(page_number, "text", text))
                report.pages_text += 1

            for _rect, markdown in tables:
                elements.append(Element(page_number, "table", markdown))
                report.tables += 1

            # text inside pictures on pages that are otherwise digital
            if ocr is not None and not is_scanned:
                for image in image_refs:
                    xref = image[0]
                    if xref in seen_images:                    # a logo repeated on every page
                        continue
                    seen_images.add(xref)

                    if ocr_images >= settings.OCR_MAX_IMAGES:
                        report.ocr_images_skipped_limit += 1
                        continue
                    png = _embedded_image_png(doc, xref)
                    if png is None:
                        report.images_skipped += 1
                        continue

                    ocr_images += 1
                    result = _recognize(ocr, png, report)
                    if result and len(result.text.strip()) >= MIN_IMAGE_TEXT_CHARS:
                        elements.append(Element(page_number, "image_text", result.text, result.confidence))
                        report.images_ocr += 1
                    else:
                        report.images_skipped += 1

    return elements


# ----------------------------------------------------------------- image files

def extract_image_elements(file_path: str, ocr: Optional[OCRProvider], report: IngestReport) -> List[Element]:
    if ocr is None:
        report.notes.append(
            "Images can only be indexed with OCR, and no OCR engine is available "
            "(pip install rapidocr-onnxruntime, and check OCR_ENABLED)."
        )
        return []

    try:
        pix = fitz.Pixmap(file_path)
    except Exception:
        report.notes.append("The file could not be read as an image.")
        return []

    if pix.width * pix.height > MAX_IMAGE_PIXELS:
        report.notes.append(f"The image is too large ({pix.width}x{pix.height} pixels).")
        return []

    if pix.colorspace is None or pix.colorspace.n != 3 or pix.alpha:
        pix = fitz.Pixmap(fitz.csRGB, pix)

    result = _recognize(ocr, pix.tobytes("png"), report)
    if result is None or not result.text.strip():
        report.notes.append("No readable text was found in the image.")
        return []

    report.pages_ocr = 1
    return [Element(None, "ocr", result.text, result.confidence)]


# -------------------------------------------------------------------- dispatch

_UNSET = object()


def extract_elements(file_path: str, filename: str, ocr: Any = _UNSET) -> Tuple[List[Element], IngestReport]:
    """
    Typed elements for an uploaded file, plus a report of what was done.
    `ocr` defaults to the configured engine (None when unavailable); tests pass their own.
    """
    if "." not in filename:
        raise ValueError(f"Cannot determine file type for: {filename}")
    extension = filename.lower().rsplit(".", 1)[-1]

    if ocr is _UNSET:
        ocr = get_ocr_provider() if extension in ("pdf",) + IMAGE_EXTENSIONS else None

    report = IngestReport(ocr_available=ocr is not None)

    if extension == "txt":
        report.source = "text"
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            text = handle.read().strip()
        return ([Element(None, "text", text)] if text else []), report

    if extension == "pdf":
        report.source = "pdf"
        elements = extract_pdf_elements(file_path, ocr, report)
    elif extension in IMAGE_EXTENSIONS:
        report.source = "image"
        elements = extract_image_elements(file_path, ocr, report)
    else:
        raise ValueError(f"Unsupported file type: {extension}")

    if report.ocr_pages_unavailable:
        report.notes.append(
            f"{report.ocr_pages_unavailable} scanned page(s) were skipped because no OCR engine is "
            f"available (pip install rapidocr-onnxruntime, and check OCR_ENABLED)."
        )
    if report.ocr_pages_skipped_limit:
        report.notes.append(
            f"{report.ocr_pages_skipped_limit} scanned page(s) were not read because the limit of "
            f"{settings.OCR_MAX_PAGES} OCR pages per document was reached (OCR_MAX_PAGES)."
        )
    if report.ocr_images_skipped_limit:
        report.notes.append(
            f"{report.ocr_images_skipped_limit} embedded image(s) were not read because the limit of "
            f"{settings.OCR_MAX_IMAGES} per document was reached (OCR_MAX_IMAGES)."
        )
    if report.ocr_errors:
        report.notes.append(f"OCR failed on {report.ocr_errors} region(s); they were skipped.")

    return elements, report