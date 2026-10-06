"""add metadata and soft delete

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("source_type", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chunks", sa.Column("page_number", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("chunks", "page_number")
    op.drop_column("documents", "deleted_at")
    op.drop_column("documents", "source_type")
    op.drop_column("documents", "page_count")