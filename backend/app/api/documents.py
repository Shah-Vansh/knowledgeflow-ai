import hashlib
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import DEFAULT_WORKSPACE_ID, get_db, require_workspace
from app.core.config import settings
from app.db.models import Document, Chunk
from app.jobs import queue
from app.rag.pipeline import ingest_document, new_document, rechunk_document

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {"pdf", "txt", "png", "jpg", "jpeg"}
UPLOAD_READ_BYTES = 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


def content_matches_extension(ext: str, head: bytes) -> bool:
    """Checks the first bytes of the upload against what the extension promises."""
    if ext == "pdf":
        return b"%PDF-" in head[:1024]
    if ext == "png":
        return head.startswith(PNG_SIGNATURE)
    if ext in {"jpg", "jpeg"}:
        return head.startswith(JPEG_SIGNATURE)
    if ext == "txt":
        return b"\x00" not in head
    return False


def find_duplicate(db: Session, workspace_id: int, sha256: str) -> Optional[Document]:
    """An active (not deleted, not failed) document in the workspace with the same bytes."""
    return (
        db.query(Document)
        .filter(
            Document.workspace_id == workspace_id,
            Document.content_sha256 == sha256,
            Document.deleted_at.is_(None),
            Document.status != "failed",
        )
        .order_by(Document.id)
        .first()
    )


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
    workspace_id: int = Form(DEFAULT_WORKSPACE_ID),
    allow_duplicate: bool = Form(False),
    db: Session = Depends(get_db),
):
    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    require_workspace(db, workspace_id)

    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
            tmp_path = tmp.name
            total = 0
            digest = hashlib.sha256()
            while True:
                block = file.file.read(UPLOAD_READ_BYTES)
                if not block:
                    break
                if total == 0 and not content_matches_extension(ext, block):
                    raise HTTPException(
                        status_code=400,
                        detail=f"File content does not match the .{ext} extension",
                    )
                total += len(block)
                if total > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is too large (limit {settings.MAX_UPLOAD_MB} MB)",
                    )
                digest.update(block)
                tmp.write(block)
            if total == 0 and not content_matches_extension(ext, b""):
                raise HTTPException(status_code=400, detail=f"File content does not match the .{ext} extension")

        sha256 = digest.hexdigest()
        if not allow_duplicate:
            existing = find_duplicate(db, workspace_id, sha256)
            if existing is not None:
                raise HTTPException(status_code=409, detail=(
                    f'This file is already in this workspace as "{existing.filename}" '
                    f"(document #{existing.id}). Delete that copy first if you want to upload it again."
                ))

        if settings.INGEST_ASYNC:
            # Store the bytes with the job and answer at once; a worker ingests it.
            # The document and its job are committed together.
            with open(tmp_path, "rb") as stored:
                file_data = stored.read()
            document = new_document(db, file.filename, workspace_id, status="queued", commit=False)
            document.content_sha256 = sha256
            job = queue.enqueue(
                db, "ingest", document.workspace_id,
                payload={"strategy": strategy, "chunk_size": chunk_size, "overlap": overlap},
                document_id=document.id, file_data=file_data,
            )
            db.commit()
            return JSONResponse(status_code=202, content={
                "document_id": document.id,
                "filename": document.filename,
                "status": document.status,
                "workspace_id": document.workspace_id,
                "ingest_report": None,
                "job_id": job.id,
            })

        document = ingest_document(
            db, tmp_path, file.filename,
            strategy=strategy, chunk_size=chunk_size, overlap=overlap,
            workspace_id=workspace_id,
        )
        document.content_sha256 = sha256
        db.commit()
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    if document.status == "failed":
        notes = (document.ingest_report or {}).get("notes") or []
        detail = "Document processing failed" + (f": {notes[0]}" if notes else "")
        raise HTTPException(status_code=422, detail=detail)

    return {
        "document_id": document.id,
        "filename": document.filename,
        "status": document.status,
        "workspace_id": document.workspace_id,
        "ingest_report": document.ingest_report,
        "job_id": None,
    }


@router.get("")
def list_documents(
    status: Optional[str] = Query(None),
    workspace_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Document).filter(Document.deleted_at.is_(None))
    if status:
        query = query.filter(Document.status == status)
    if workspace_id is not None:
        query = query.filter(Document.workspace_id == workspace_id)
    documents = query.order_by(Document.id).all()

    return [
        {
            "id": d.id,
            "filename": d.filename,
            "status": d.status,
            "page_count": d.page_count,
            "source_type": d.source_type,
            "workspace_id": d.workspace_id,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "ingest_report": d.ingest_report,
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
            "chunk_type": c.chunk_type,
            "ocr_confidence": c.ocr_confidence,
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