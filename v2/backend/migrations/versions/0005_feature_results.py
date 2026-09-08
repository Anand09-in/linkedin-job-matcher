"""feature_results — on-demand feature cache (FR-6.3, Phase 6)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("feature", sa.String(50), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("params_key", sa.String(255), nullable=False, server_default=""),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_feature_results_job_id", "feature_results", ["job_id"])
    # Lookup index for the exact cache-key query (Repository.get_cached_feature_result)
    # — not a unique index, see FeatureResult's docstring for why (NULL resume_id).
    op.create_index(
        "ix_feature_results_lookup", "feature_results", ["job_id", "resume_id", "feature", "params_key"]
    )


def downgrade() -> None:
    op.drop_table("feature_results")
