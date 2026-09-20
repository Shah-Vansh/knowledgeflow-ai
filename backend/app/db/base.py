from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models.

    Intentionally empty in Phase 0 — no models exist yet.
    Phase 1 will add Document and Chunk models here.
    """
    pass