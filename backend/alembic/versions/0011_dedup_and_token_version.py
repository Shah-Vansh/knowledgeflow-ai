"""duplicate-upload detection and token revocation

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    # Existing documents keep NULL (their bytes weren't kept); new uploads get a hash.
    op.add_column("documents", sa.Column("content_sha256", sa.String(64), nullable=True))
    op.create_index("ix_documents_workspace_sha256", "documents", ["workspace_id", "content_sha256"],
                    postgresql_where=sa.text("content_sha256 IS NOT NULL AND deleted_at IS NULL"))
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("users", "token_version")
    op.drop_index("ix_documents_workspace_sha256", table_name="documents")
    op.drop_column("documents", "content_sha256")
