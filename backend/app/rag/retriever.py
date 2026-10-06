from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.db.models import Chunk, Document


def retrieve_top_k(
    db: Session,
    query_embedding: List[float],
    k: int = 5,
    document_ids: Optional[List[int]] = None,
) -> List[Tuple[Chunk, float]]:
    """
    Cosine-distance similarity search. Always excludes chunks belonging
    to soft-deleted documents. Optionally restricts to a specific set
    of document_ids.
    """
    query = (
        db.query(Chunk, Chunk.embedding.cosine_distance(query_embedding).label("distance"))
        .join(Document, Chunk.document_id == Document.id)
        .filter(Document.deleted_at.is_(None))
    )

    if document_ids:
        query = query.filter(Chunk.document_id.in_(document_ids))

    results = (
        query.order_by(Chunk.embedding.cosine_distance(query_embedding))
        .limit(k)
        .all()
    )
    return results