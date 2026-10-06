from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.rag.pipeline import answer_question

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    question: str
    document_ids: Optional[List[int]] = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/query")
def query(request: QueryRequest, db: Session = Depends(get_db)):
    return answer_question(db, request.question, document_ids=request.document_ids)