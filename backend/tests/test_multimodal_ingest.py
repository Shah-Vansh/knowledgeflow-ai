import fitz
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.models import Chunk, Document
from app.db.session import SessionLocal
from app.main import app
from app.rag.chunker import chunk_text
from app.rag.multimodal import Element, IngestReport, OCRResult, table_to_markdown
from app.rag.pipeline import ingest_document, rechunk_document
from app.rag.retriever import retrieve_bm25
from tests.graph_helpers import cleanup_workspaces, make_workspace
from tests.multimodal_helpers import (
    FakeOCR,
    make_scanned_pdf,
    make_table_pdf,
    make_text_pdf,
    render_lines_png,
)

client = TestClient(app)


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def workspace_ids():
    ids = []
    yield ids
    cleanup_workspaces(ids)


@pytest.fixture
def workspace_id(db_session, workspace_ids):
    return make_workspace(db_session, workspace_ids, "multimodal")


def use_ocr(monkeypatch, provider):
    monkeypatch.setattr("app.rag.multimodal.get_ocr_provider", lambda: provider)


def chunks_of(session, document):
    return session.query(Chunk).filter(Chunk.document_id == document.id).order_by(Chunk.chunk_index).all()


# ------------------------------------------------------------------ ingestion

def test_scanned_pdf_is_stored_as_ocr_chunks(db_session, workspace_id, tmp_path, monkeypatch):
    use_ocr(monkeypatch, FakeOCR(results=[OCRResult("INVOICE 48213", 0.95, 1), OCRResult("Total due 450", 0.8, 1)]))
    path = make_scanned_pdf(str(tmp_path / "scan.pdf"), [["INVOICE 48213"], ["Total due 450"]])

    document = ingest_document(db_session, path, "scan.pdf", workspace_id=workspace_id)

    assert document.status == "processed" and document.source_type == "pdf" and document.page_count == 2
    chunks = chunks_of(db_session, document)
    assert [(c.chunk_type, c.page_number, c.content) for c in chunks] == [
        ("ocr", 1, "INVOICE 48213"), ("ocr", 2, "Total due 450"),
    ]
    assert [c.ocr_confidence for c in chunks] == [0.95, 0.8]
    assert document.ingest_report["pages_ocr"] == 2 and document.ingest_report["ocr_available"] is True
    assert "INVOICE 48213" in document.raw_text and "Total due 450" in document.raw_text


def test_table_pdf_is_stored_as_text_and_table_chunks_and_is_searchable(db_session, workspace_id, tmp_path, monkeypatch):
    use_ocr(monkeypatch, None)
    path = make_table_pdf(str(tmp_path / "table.pdf"))

    document = ingest_document(db_session, path, "table.pdf", workspace_id=workspace_id)

    chunks = chunks_of(db_session, document)
    by_type = {c.chunk_type: c for c in chunks}
    assert set(by_type) == {"text", "table"}
    assert "| South | 950 | 8% |" in by_type["table"].content
    assert "950" not in by_type["text"].content and "Revenue grew across all regions" in by_type["text"].content
    assert by_type["table"].ocr_confidence is None and by_type["table"].page_number == 1
    assert document.ingest_report["tables"] == 1

    # numbers inside a table are found by keyword search
    hits = retrieve_bm25(db_session, "950", k=5, workspace_id=workspace_id)
    assert [(c.chunk_type, c.document_id) for c, _ in hits] == [("table", document.id)]


def test_digital_pdf_and_text_files_are_chunked_exactly_as_before(db_session, workspace_id, tmp_path, monkeypatch):
    use_ocr(monkeypatch, FakeOCR())
    long_text = " ".join(f"alpha{i}" for i in range(260))                # > 500 characters: several chunks
    pdf = make_text_pdf(str(tmp_path / "digital.pdf"), [long_text, "", "Third page about oranges."])

    document = ingest_document(db_session, pdf, "digital.pdf", workspace_id=workspace_id)

    with fitz.open(pdf) as doc:
        pages = [(i, p.get_text().strip()) for i, p in enumerate(doc, start=1) if p.get_text().strip()]
    expected = [(piece, number) for number, text in pages for piece in chunk_text(text, "fixed_size", 500, 0)]
    chunks = chunks_of(db_session, document)
    assert [(c.content, c.page_number) for c in chunks] == expected
    assert len(chunks) > 2 and {c.chunk_type for c in chunks} == {"text"}
    assert all(c.ocr_confidence is None for c in chunks)
    assert document.page_count == 3

    notes = tmp_path / "notes.txt"
    notes.write_text("Plain text file content. " * 50, encoding="utf-8")
    text_document = ingest_document(db_session, str(notes), "notes.txt", workspace_id=workspace_id)
    expected_text = chunk_text(notes.read_text(encoding="utf-8").strip(), "fixed_size", 500, 0)
    assert [c.content for c in chunks_of(db_session, text_document)] == expected_text
    assert text_document.page_count is None and text_document.source_type == "txt"


def test_page_text_keeps_the_documents_own_reading_order(db_session, workspace_id, tmp_path, monkeypatch):
    """Text must come out exactly as page.get_text() returns it (content-stream order), not re-sorted."""
    use_ocr(monkeypatch, None)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 700), "Bottom line written first.", fontsize=12)
    page.insert_text((72, 100), "Top line written second.", fontsize=12)
    path = str(tmp_path / "order.pdf")
    doc.save(path)
    doc.close()

    document = ingest_document(db_session, path, "order.pdf", workspace_id=workspace_id)

    with fitz.open(path) as reopened:
        expected = reopened[0].get_text().strip()
    assert expected.index("Bottom") < expected.index("Top")             # the fixture really is out of visual order
    assert document.raw_text == expected
    assert [c.content for c in chunks_of(db_session, document)] == [expected]


def test_a_large_table_is_chunked_by_rows_with_the_header_repeated(db_session, workspace_id, tmp_path, monkeypatch):
    rows = [["Item", "Description"]] + [[f"item{i:03d}", f"description number {i} " + "word " * 12] for i in range(60)]
    markdown = table_to_markdown(rows)
    assert len(markdown) > 3000
    monkeypatch.setattr(
        "app.rag.pipeline.extract_elements", lambda path, name: ([Element(1, "table", markdown)], IngestReport())
    )
    path = tmp_path / "big_table.pdf"
    path.write_bytes(b"unused")

    document = ingest_document(db_session, str(path), "big_table.pdf", workspace_id=workspace_id)

    chunks = chunks_of(db_session, document)
    header = "\n".join(markdown.split("\n")[:2])
    assert len(chunks) > 1 and {c.chunk_type for c in chunks} == {"table"}
    assert all(c.content.startswith(header) and len(c.content) <= 2000 for c in chunks)
    joined = "\n".join(c.content for c in chunks)
    assert all(f"item{i:03d}" in joined for i in range(60))             # no row lost


def test_a_scan_without_an_ocr_engine_fails_with_an_explanation(db_session, workspace_id, tmp_path, monkeypatch):
    use_ocr(monkeypatch, None)
    path = make_scanned_pdf(str(tmp_path / "scan.pdf"), [["INVOICE 48213"]])

    document = ingest_document(db_session, path, "scan.pdf", workspace_id=workspace_id)

    assert document.status == "failed"
    assert chunks_of(db_session, document) == []
    assert any("no OCR engine" in note for note in document.ingest_report["notes"])


def test_a_corrupt_pdf_fails_cleanly_with_a_note(db_session, workspace_id, tmp_path, monkeypatch):
    use_ocr(monkeypatch, None)
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 this is not really a pdf")

    document = ingest_document(db_session, str(path), "broken.pdf", workspace_id=workspace_id)

    assert document.status == "failed"
    assert document.ingest_report["notes"][0].startswith("Processing failed")


def test_rechunking_flattens_every_chunk_to_plain_text(db_session, workspace_id, tmp_path, monkeypatch):
    use_ocr(monkeypatch, None)
    path = make_table_pdf(str(tmp_path / "table.pdf"))
    document = ingest_document(db_session, path, "table.pdf", workspace_id=workspace_id)
    assert {c.chunk_type for c in chunks_of(db_session, document)} == {"text", "table"}

    rechunk_document(db_session, document.id, "fixed_size", 500, 0)

    db_session.expire_all()
    assert {c.chunk_type for c in chunks_of(db_session, document)} == {"text"}       # documented limitation


# ------------------------------------------------------------------------ API

def upload(workspace_id, name, content, content_type="application/octet-stream", **extra):
    return client.post(
        "/documents/upload",
        files={"file": (name, content, content_type)},
        data={"workspace_id": str(workspace_id), **extra},
    )


def test_uploading_an_image_returns_the_report_and_typed_chunks(workspace_id, monkeypatch):
    use_ocr(monkeypatch, FakeOCR(default=OCRResult("TOTAL 450", 0.97, 1)))

    response = upload(workspace_id, "receipt.png", render_lines_png(["TOTAL 450"]), "image/png")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processed" and body["ingest_report"]["source"] == "image"

    listed = [d for d in client.get(f"/documents?workspace_id={workspace_id}").json() if d["id"] == body["document_id"]][0]
    assert listed["source_type"] == "image" and listed["page_count"] is None
    assert listed["ingest_report"]["pages_ocr"] == 1

    chunks = client.get(f"/documents/{body['document_id']}/chunks").json()
    assert [(c["chunk_type"], c["ocr_confidence"], c["page_number"], c["content"]) for c in chunks] == [
        ("ocr", 0.97, None, "TOTAL 450"),
    ]


def test_uploading_a_scan_without_ocr_returns_422_with_the_reason(workspace_id, tmp_path, monkeypatch):
    use_ocr(monkeypatch, None)
    path = make_scanned_pdf(str(tmp_path / "scan.pdf"), [["INVOICE 48213"]])

    with open(path, "rb") as handle:
        response = upload(workspace_id, "scan.pdf", handle.read(), "application/pdf")

    assert response.status_code == 422
    assert "no OCR engine" in response.json()["detail"]

    failed = [d for d in client.get(f"/documents?workspace_id={workspace_id}").json() if d["filename"] == "scan.pdf"]
    assert len(failed) == 1 and failed[0]["status"] == "failed"
    assert any("no OCR engine" in n for n in failed[0]["ingest_report"]["notes"])


def test_upload_size_limit(workspace_id, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 0)

    response = upload(workspace_id, "big.txt", b"some content", "text/plain")

    assert response.status_code == 413
    assert "too large" in response.json()["detail"]
    assert client.get(f"/documents?workspace_id={workspace_id}").json() == []         # nothing was created


def test_upload_validation_and_workspace_handling(workspace_id):
    bad = upload(workspace_id, "notes.docx", b"data")
    assert bad.status_code == 400
    assert all(ext in bad.json()["detail"] for ext in ("png", "jpg", "jpeg", "pdf", "txt"))

    assert upload(999999, "notes.txt", b"hello world content", "text/plain").status_code == 404

    ok = upload(workspace_id, "notes.txt", b"Plain text file about gardening and plants.", "text/plain")
    assert ok.status_code == 200 and ok.json()["workspace_id"] == workspace_id
    assert ok.json()["ingest_report"]["source"] == "text"

    other_workspace = client.get("/documents?workspace_id=1").json()
    assert ok.json()["document_id"] not in [d["id"] for d in other_workspace]