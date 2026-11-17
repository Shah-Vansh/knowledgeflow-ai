import fitz
import pytest

from app.core.config import settings
from app.rag import multimodal
from app.rag.multimodal import (
    MAX_TABLE_CHARS,
    OCRResult,
    assemble_ocr_result,
    chunk_table,
    extract_elements,
    get_ocr_provider,
    table_to_markdown,
)
from tests.multimodal_helpers import (
    FakeOCR,
    make_pdf_with_images,
    make_png_file,
    make_scanned_pdf,
    make_table_pdf,
    make_text_pdf,
)


def kinds(elements):
    return [e.kind for e in elements]


# ------------------------------------------------------------ OCR assembly

def test_assemble_ocr_result_filters_low_confidence_and_averages():
    result = assemble_ocr_result(
        [("clear line", 0.9), ("  ", 0.99), ("noise", 0.2), ("another clear line", 0.7), ("", 0.9)],
        min_confidence=0.5,
    )
    assert result.text == "clear line\nanother clear line"
    assert result.lines == 2
    assert result.confidence == pytest.approx(0.8)


def test_assemble_ocr_result_with_nothing_usable():
    assert assemble_ocr_result([("x", 0.1)], 0.5) == OCRResult(text="", confidence=0.0, lines=0)
    assert assemble_ocr_result([], 0.5).lines == 0


def test_get_ocr_provider_respects_the_switch(monkeypatch):
    monkeypatch.setattr(settings, "OCR_ENABLED", False)
    assert get_ocr_provider() is None


# ------------------------------------------------------------------ tables

def test_table_to_markdown_basic_and_cleaning():
    markdown = table_to_markdown([
        ["Region", "Revenue | USD", None],
        ["North", "1,200", ""],
        ["", "", ""],                      # empty row dropped
        ["South", "950\n(est.)"],          # ragged row padded, newline collapsed
    ])
    assert markdown.split("\n") == [
        "| Region | Revenue / USD |",
        "| --- | --- |",
        "| North | 1,200 |",
        "| South | 950 (est.) |",
    ]


@pytest.mark.parametrize(
    "rows",
    [[], [["only one row", "x"]], [["a"], ["b"]], [["", ""], ["", ""]], [[None, None], [None, None]]],
)
def test_table_to_markdown_rejects_things_that_are_not_tables(rows):
    assert table_to_markdown(rows) == ""


def test_small_table_stays_in_one_chunk():
    markdown = table_to_markdown([["A", "B"], ["1", "2"], ["3", "4"]])
    assert chunk_table(markdown) == [markdown]


def test_large_table_is_split_by_rows_and_every_piece_repeats_the_header():
    rows = [["Name", "Value"]] + [[f"item{i:04d}", f"value-{i:04d}-" + "x" * 40] for i in range(200)]
    markdown = table_to_markdown(rows)
    assert len(markdown) > MAX_TABLE_CHARS

    chunks = chunk_table(markdown)

    assert len(chunks) > 1
    header = "\n".join(markdown.split("\n")[:2])
    for chunk in chunks:
        assert chunk.startswith(header)
        assert len(chunk) <= MAX_TABLE_CHARS
    joined = "\n".join(chunks)
    for i in range(200):
        assert f"item{i:04d}" in joined                    # no row was lost


def test_a_single_enormous_row_is_truncated_not_dropped():
    markdown = table_to_markdown([["A", "B"], ["short", "x"], ["huge", "y" * 5000]])
    chunks = chunk_table(markdown, max_chars=300)
    assert all(len(c) <= 300 for c in chunks)
    assert any("huge" in c for c in chunks)


# ---------------------------------------------------------- plain and digital

def test_text_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("  Hello world.  ", encoding="utf-8")
    elements, report = extract_elements(str(path), "notes.txt")

    assert [(e.page_number, e.kind, e.text) for e in elements] == [(None, "text", "Hello world.")]
    assert report.source == "text" and report.ocr_available is False


def test_empty_text_file_has_no_elements(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n  ", encoding="utf-8")
    assert extract_elements(str(path), "empty.txt")[0] == []


@pytest.mark.parametrize("name", ["noextension", "archive.zip", "doc.docx"])
def test_unsupported_names_raise(tmp_path, name):
    path = tmp_path / "x"
    path.write_bytes(b"data")
    with pytest.raises(ValueError):
        extract_elements(str(path), name)


def test_digital_pdf_is_extracted_exactly_as_before_and_never_ocrd(tmp_path):
    path = make_text_pdf(str(tmp_path / "digital.pdf"), ["First page text about apples.", "", "Third page about oranges."])
    ocr = FakeOCR()

    elements, report = extract_elements(path, "digital.pdf", ocr=ocr)

    with fitz.open(path) as doc:
        expected = [(i, p.get_text().strip()) for i, p in enumerate(doc, start=1) if p.get_text().strip()]
    assert [(e.page_number, e.text) for e in elements] == expected      # identical to page.get_text()
    assert kinds(elements) == ["text", "text"]
    assert (report.pages_total, report.pages_text, report.pages_ocr) == (3, 2, 0)
    assert ocr.calls == 0 and report.notes == []                        # blank page: no OCR, no noise


# ----------------------------------------------------------------- scanned

def test_scanned_pages_are_read_with_ocr(tmp_path):
    path = make_scanned_pdf(str(tmp_path / "scan.pdf"), [["INVOICE 48213"], ["Page two content"]])
    ocr = FakeOCR(results=[OCRResult("INVOICE 48213", 0.95, 1), OCRResult("Page two content", 0.8, 1)])

    elements, report = extract_elements(path, "scan.pdf", ocr=ocr)

    assert [(e.page_number, e.kind, e.text) for e in elements] == [
        (1, "ocr", "INVOICE 48213"), (2, "ocr", "Page two content"),
    ]
    assert [e.confidence for e in elements] == [0.95, 0.8]
    assert (report.pages_total, report.pages_ocr, report.pages_text, report.ocr_available) == (2, 2, 0, True)
    assert ocr.calls == 2


def test_scanned_pdf_without_an_ocr_engine_is_reported_not_silent(tmp_path):
    path = make_scanned_pdf(str(tmp_path / "scan.pdf"), [["INVOICE 48213"], ["Page two"]])

    elements, report = extract_elements(path, "scan.pdf", ocr=None)

    assert elements == []
    assert report.ocr_available is False and report.ocr_pages_unavailable == 2
    assert any("no OCR engine" in note for note in report.notes)


def test_ocr_page_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OCR_MAX_PAGES", 1)
    path = make_scanned_pdf(str(tmp_path / "scan.pdf"), [["one"], ["two"], ["three"]])
    ocr = FakeOCR()

    elements, report = extract_elements(path, "scan.pdf", ocr=ocr)

    assert kinds(elements) == ["ocr"] and ocr.calls == 1
    assert report.ocr_pages_skipped_limit == 2
    assert any("OCR_MAX_PAGES" in note for note in report.notes)


def test_ocr_that_reads_nothing_or_crashes_does_not_break_ingestion(tmp_path):
    path = make_scanned_pdf(str(tmp_path / "scan.pdf"), [["a"], ["b"], ["c"]])
    ocr = FakeOCR(results=[OCRResult("", 0.0, 0), RuntimeError("engine crashed"), OCRResult("page three", 0.9, 1)])

    elements, report = extract_elements(path, "scan.pdf", ocr=ocr)

    assert [(e.page_number, e.text) for e in elements] == [(3, "page three")]
    assert report.ocr_errors == 1
    assert any("OCR failed on 1 region" in note for note in report.notes)


# ------------------------------------------------------- images inside pages

def test_text_inside_an_embedded_image_becomes_image_text(tmp_path):
    path = make_pdf_with_images(str(tmp_path / "chart.pdf"), ["Body text of the page."], ["Revenue chart", "Q1 to Q4"])
    ocr = FakeOCR(default=OCRResult("Revenue chart Q1 to Q4 labels", 0.9, 2))

    elements, report = extract_elements(path, "chart.pdf", ocr=ocr)

    assert kinds(elements) == ["text", "image_text"]
    assert elements[1].text == "Revenue chart Q1 to Q4 labels" and elements[1].page_number == 1
    assert report.images_ocr == 1 and report.pages_ocr == 0


def test_tiny_images_repeated_images_and_noise_are_not_ocrd_or_kept(tmp_path):
    path = make_pdf_with_images(
        str(tmp_path / "logo.pdf"), ["Page one.", "Page two.", "Page three."], ["Some chart"],
        repeat_same_image=True, add_logo=True,
    )
    ocr = FakeOCR(default=OCRResult("short", 0.9, 1))                  # < 15 characters: noise

    elements, report = extract_elements(path, "logo.pdf", ocr=ocr)

    assert kinds(elements) == ["text", "text", "text"]                 # nothing kept from images
    assert ocr.calls == 1                                              # logo skipped, repeats skipped
    assert report.images_ocr == 0 and report.images_skipped == 2       # the logo and the noisy chart


def test_embedded_image_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OCR_MAX_IMAGES", 1)
    doc = fitz.open()
    for i in range(3):                       # three different pictures on three pages
        page = doc.new_page()
        page.insert_text((72, 80), f"Page {i}", fontsize=12)
        from tests.multimodal_helpers import render_lines_png
        page.insert_image(fitz.Rect(72, 300, 472, 500), stream=render_lines_png([f"picture {i}"], 400, 200, 18))
    path = str(tmp_path / "many.pdf")
    doc.save(path)
    doc.close()
    ocr = FakeOCR(default=OCRResult("text inside a picture here", 0.9, 1))

    elements, report = extract_elements(path, "many.pdf", ocr=ocr)

    assert kinds(elements).count("image_text") == 1 and ocr.calls == 1
    assert report.ocr_images_skipped_limit == 2
    assert any("OCR_MAX_IMAGES" in note for note in report.notes)


def test_a_short_digital_page_with_a_picture_is_not_mistaken_for_a_scan(tmp_path):
    """A title plus a chart is a digital page: its perfect text must be kept, not replaced by OCR."""
    path = make_pdf_with_images(str(tmp_path / "title.pdf"), ["Results"], ["Revenue chart", "Q1 to Q4"])
    ocr = FakeOCR(default=OCRResult("Revenue chart Q1 to Q4 labels", 0.9, 2))

    elements, report = extract_elements(path, "title.pdf", ocr=ocr)

    assert kinds(elements) == ["text", "image_text"]
    assert elements[0].text == "Results"
    assert report.pages_ocr == 0 and report.pages_text == 1


# ------------------------------------------------------------------- tables

def test_table_pages_yield_a_table_element_and_text_without_the_table(tmp_path):
    path = make_table_pdf(str(tmp_path / "table.pdf"))

    elements, report = extract_elements(path, "table.pdf", ocr=None)

    assert kinds(elements) == ["text", "table"]
    text, table = elements[0].text, elements[1].text
    assert "Quarterly report" in text and "Revenue grew across all regions" in text
    assert "1200" not in text and "Region" not in text                 # no duplication
    assert table.split("\n")[:2] == ["| Region | Revenue | Growth |", "| --- | --- | --- |"]
    assert "| North | 1200 | 12% |" in table and "| East | 1400 | 15% |" in table
    assert report.tables == 1 and report.pages_text == 1


def test_tables_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "TABLES_ENABLED", False)
    path = make_table_pdf(str(tmp_path / "table.pdf"))

    elements, report = extract_elements(path, "table.pdf", ocr=None)

    assert kinds(elements) == ["text"] and report.tables == 0
    assert "1200" in elements[0].text                                   # old behavior: flattened into text


# -------------------------------------------------------------- image files

def test_image_file_is_read_with_ocr(tmp_path):
    path = make_png_file(str(tmp_path / "receipt.png"), ["TOTAL 450"])
    ocr = FakeOCR(default=OCRResult("TOTAL 450", 0.97, 1))

    elements, report = extract_elements(path, "receipt.png", ocr=ocr)

    assert [(e.page_number, e.kind, e.text, e.confidence) for e in elements] == [(None, "ocr", "TOTAL 450", 0.97)]
    assert report.source == "image" and report.pages_ocr == 1


def test_image_file_without_ocr_or_with_no_text_or_corrupt(tmp_path):
    path = make_png_file(str(tmp_path / "receipt.png"), ["TOTAL 450"])

    elements, report = extract_elements(path, "receipt.png", ocr=None)
    assert elements == [] and any("OCR" in n for n in report.notes)

    elements, report = extract_elements(path, "receipt.png", ocr=FakeOCR(default=OCRResult("", 0.0, 0)))
    assert elements == [] and any("No readable text" in n for n in report.notes)

    broken = tmp_path / "broken.png"
    broken.write_bytes(b"this is not an image")
    elements, report = extract_elements(str(broken), "broken.png", ocr=FakeOCR())
    assert elements == [] and any("could not be read" in n for n in report.notes)


def test_oversized_images_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(multimodal, "MAX_IMAGE_PIXELS", 1000)
    path = make_png_file(str(tmp_path / "big.png"), ["TOTAL 450"])
    ocr = FakeOCR()

    elements, report = extract_elements(path, "big.png", ocr=ocr)

    assert elements == [] and ocr.calls == 0
    assert any("too large" in n for n in report.notes)


# -------------------------------------------------------------- the real engine

def test_real_ocr_reads_a_scanned_pdf_and_an_image_file(tmp_path):
    pytest.importorskip("rapidocr_onnxruntime")
    provider = get_ocr_provider()
    assert provider is not None

    pdf = make_scanned_pdf(str(tmp_path / "scan.pdf"), [["INVOICE NUMBER 48213", "Total amount due: 450 dollars"]])
    elements, report = extract_elements(pdf, "scan.pdf", ocr=provider)

    assert kinds(elements) == ["ocr"]
    text = elements[0].text.lower()
    assert "invoice" in text and "48213" in text and "450" in text
    assert elements[0].confidence > 0.8
    assert report.pages_ocr == 1

    png = make_png_file(str(tmp_path / "scan.png"), ["Quarterly revenue grew by twelve percent"])
    image_elements, _ = extract_elements(png, "scan.png", ocr=provider)
    assert "revenue" in image_elements[0].text.lower() and "twelve" in image_elements[0].text.lower()