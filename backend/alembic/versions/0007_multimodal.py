"""multimodal ingestion: chunk types, OCR confidence, ingest report

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    # existing chunks are all plain text
    op.add_column("chunks", sa.Column("chunk_type", sa.String(), nullable=False, server_default="text"))
    op.add_column("chunks", sa.Column("ocr_confidence", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("ingest_report", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("documents", "ingest_report")
    op.drop_column("chunks", "ocr_confidence")
    op.drop_column("chunks", "chunk_type")