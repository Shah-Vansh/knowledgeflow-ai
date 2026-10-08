"""add search_vector generated column for full-text search

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    # GENERATED ALWAYS AS ... STORED means PostgreSQL computes this column
    # automatically from `content` on every insert/update — no application
    # code needs to populate it. Adding it also backfills every existing
    # row as part of this single ALTER TABLE.
    op.execute("""
        ALTER TABLE chunks
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
    """)
    op.execute("CREATE INDEX ix_chunks_search_vector ON chunks USING GIN (search_vector)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_chunks_search_vector")
    op.execute("ALTER TABLE chunks DROP COLUMN search_vector")