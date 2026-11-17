"""background job queue (production runtime)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("workspace_id", sa.Integer(),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("file_data", sa.LargeBinary(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_by", sa.String(128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')", name="ck_jobs_status"
        ),
        sa.CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_jobs_attempts"),
    )
    op.create_index("ix_jobs_workspace_id", "jobs", ["workspace_id"])
    op.create_index("ix_jobs_document_id", "jobs", ["document_id"])
    # The claim query scans only queued jobs, oldest first.
    op.create_index("ix_jobs_queued", "jobs", ["run_after", "id"],
                    postgresql_where=sa.text("status = 'queued'"))


def downgrade():
    op.drop_index("ix_jobs_queued", table_name="jobs")
    op.drop_index("ix_jobs_document_id", table_name="jobs")
    op.drop_index("ix_jobs_workspace_id", table_name="jobs")
    op.drop_table("jobs")
