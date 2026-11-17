"""evaluation sets, runs and experiments

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "eval_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_sets_workspace_id", "eval_sets", ["workspace_id"])

    op.create_table(
        "eval_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("eval_set_id", sa.Integer(), sa.ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("should_refuse", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_questions_eval_set_id", "eval_questions", ["eval_set_id"])

    op.create_table(
        "experiments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("eval_set_id", sa.Integer(), sa.ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("variants", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_experiments_eval_set_id", "experiments", ["eval_set_id"])

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("eval_set_id", sa.Integer(), sa.ForeignKey("eval_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("variant_index", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("elapsed_ms", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_runs_eval_set_id", "eval_runs", ["eval_set_id"])
    op.create_index("ix_eval_runs_experiment_id", "eval_runs", ["experiment_id"])

    op.create_table(
        "eval_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("eval_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_eval_results_run_id", "eval_results", ["run_id"])
    op.create_index("ix_eval_results_question_id", "eval_results", ["question_id"])


def downgrade():
    op.drop_table("eval_results")
    op.drop_table("eval_runs")
    op.drop_table("experiments")
    op.drop_table("eval_questions")
    op.drop_table("eval_sets")