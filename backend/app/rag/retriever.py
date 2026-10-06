from typing import List, Tuple

from sqlalchemy.orm import Session

from app.db.models import Chunk


def retrieve_top_k(db: Session, query_embedding: List[float], k: int = 5) -> List[Tuple[Chunk, float]]:
    """
    Cosine-distance similarity search using pgvector's <=> operator
    (exposed here via SQLAlchemy's .cosine_distance() comparator).
    Lower distance = more similar. Returns [(Chunk, distance), ...].
    """
    results = (
        db.query(Chunk, Chunk.embedding.cosine_distance(query_embedding).label("distance"))
        .order_by(Chunk.embedding.cosine_distance(query_embedding))
        .limit(k)
        .all()
    )
    return results