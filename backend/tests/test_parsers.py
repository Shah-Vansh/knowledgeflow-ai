import fitz

from app.rag.parsers import extract_text_from_txt, extract_text_from_pdf, extract_text


def test_extract_text_from_txt(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Hello world from a text file.")
    result = extract_text_from_txt(str(file_path))
    assert "Hello world" in result


def test_extract_text_from_pdf(tmp_path):
    file_path = tmp_path / "sample.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello world from a PDF file.")
    doc.save(str(file_path))
    doc.close()

    result = extract_text_from_pdf(str(file_path))
    assert "Hello world" in result


def test_extract_text_dispatches_by_extension(tmp_path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("dispatch test")
    result = extract_text(str(file_path), "sample.txt")
    assert "dispatch test" in result