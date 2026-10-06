"""add chunking params and raw_text

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("raw_text", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("strategy", sa.String(), nullable=True))
    op.add_column("chunks", sa.Column("chunk_size", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("overlap", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("chunks", "overlap")
    op.drop_column("chunks", "chunk_size")
    op.drop_column("chunks", "strategy")
    op.drop_column("documents", "raw_text")