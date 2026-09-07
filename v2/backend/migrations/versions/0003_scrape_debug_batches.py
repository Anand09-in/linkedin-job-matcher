"""scrape_debug_batches (Phase 2 wiring-check table)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scrape_debug_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("jobs", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_scrape_debug_batches_pipeline_id", "scrape_debug_batches", ["pipeline_id"])


def downgrade() -> None:
    op.drop_table("scrape_debug_batches")
