"""knowledge graph: entities, relationships, chunk_entities

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False, server_default="OTHER"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "normalized_name", name="uq_entities_workspace_name"),
    )
    op.create_index("ix_entities_workspace_id", "entities", ["workspace_id"])
    op.create_index("ix_entities_normalized_name", "entities", ["normalized_name"])

    op.create_table(
        "relationships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_id", sa.Integer(), sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_relationships_workspace_id", "relationships", ["workspace_id"])
    op.create_index("ix_relationships_document_id", "relationships", ["document_id"])
    op.create_index("ix_relationships_chunk_id", "relationships", ["chunk_id"])
    op.create_index("ix_relationships_source_id", "relationships", ["source_id"])
    op.create_index("ix_relationships_target_id", "relationships", ["target_id"])

    op.create_table(
        "chunk_entities",
        sa.Column("chunk_id", sa.Integer(), sa.ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_chunk_entities_entity_id", "chunk_entities", ["entity_id"])


def downgrade():
    op.drop_index("ix_chunk_entities_entity_id", table_name="chunk_entities")
    op.drop_table("chunk_entities")
    for name in ("target_id", "source_id", "chunk_id", "document_id", "workspace_id"):
        op.drop_index(f"ix_relationships_{name}", table_name="relationships")
    op.drop_table("relationships")
    op.drop_index("ix_entities_normalized_name", table_name="entities")
    op.drop_index("ix_entities_workspace_id", table_name="entities")
    op.drop_table("entities")