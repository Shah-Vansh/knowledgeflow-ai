"""workspaces, conversations and messages

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    # --- workspaces, with a default workspace that owns every existing document ---
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("name", name="uq_workspaces_name"),
    )
    op.execute(
        "INSERT INTO workspaces (id, name, description) "
        "VALUES (1, 'General', 'Default workspace')"
    )
    # explicit id above does not advance the sequence: next created workspace gets id 2
    op.execute("SELECT setval(pg_get_serial_sequence('workspaces', 'id'), 1)")

    # NOT NULL with a server default backfills every existing document into workspace 1
    op.add_column(
        "documents",
        sa.Column("workspace_id", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_foreign_key(
        "fk_documents_workspace_id", "documents", "workspaces", ["workspace_id"], ["id"]
    )
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])

    # --- conversations and messages ---
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversations_workspace_id", "conversations", ["workspace_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", postgresql.JSONB(), nullable=True),
        sa.Column("standalone_question", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])


def downgrade():
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_workspace_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_documents_workspace_id", table_name="documents")
    op.drop_constraint("fk_documents_workspace_id", "documents", type_="foreignkey")
    op.drop_column("documents", "workspace_id")
    op.drop_table("workspaces")