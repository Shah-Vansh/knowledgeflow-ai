import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.models import Document, Chunk
from app.rag.pipeline import ingest_document, rechunk_document

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {"pdf", "txt"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class RechunkRequest(BaseModel):
    strategy: str = "fixed_size"
    chunk_size: int = 500
    overlap: int = 0


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    strategy: str = Form("fixed_size"),
    chunk_size: int = Form(500),
    overlap: int = Form(0),
    db: Session = Depends(get_db),
):
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{ext}. Allowed: pdf, txt",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        document = ingest_document(
            db, tmp_path, file.filename,
            strategy=strategy, chunk_size=chunk_size, overlap=overlap,
        )
    finally:
        os.remove(tmp_path)

    if document.status == "failed":
        raise HTTPException(status_code=422, detail="Document processing failed")

    return {"document_id": document.id, "filename": document.filename, "status": document.status}


@router.get("")
def list_documents(status: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(Document).filter(Document.deleted_at.is_(None))
    if status:
        query = query.filter(Document.status == status)
    documents = query.order_by(Document.id).all()

    return [
        {
            "id": d.id,
            "filename": d.filename,
            "status": d.status,
            "page_count": d.page_count,
            "source_type": d.source_type,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
        }
        for d in documents
    ]


@router.get("/{document_id}/chunks")
def get_document_chunks(document_id: int, db: Session = Depends(get_db)):
    chunks = (
        db.query(Chunk)
        .filter(Chunk.document_id == document_id)
        .order_by(Chunk.chunk_index)
        .all()
    )
    return [
        {
            "id": c.id,
            "chunk_index": c.chunk_index,
            "content": c.content,
            "strategy": c.strategy,
            "chunk_size": c.chunk_size,
            "overlap": c.overlap,
            "page_number": c.page_number,
        }
        for c in chunks
    ]


@router.post("/{document_id}/rechunk")
def rechunk(document_id: int, request: RechunkRequest, db: Session = Depends(get_db)):
    try:
        result = rechunk_document(
            db, document_id,
            strategy=request.strategy,
            chunk_size=request.chunk_size,
            overlap=request.overlap,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return result


@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.deleted_at.is_(None))
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    db.query(Chunk).filter(Chunk.document_id == document_id).delete()
    document.deleted_at = datetime.now(timezone.utc)
    db.commit()

    return {"document_id": document_id, "deleted": True}