"""rejected_jobs.experience_years_min — so a rejection reason of
"exceeds_max_experience_years" can show the actual value that triggered it,
alongside match_score for "below_match_score_threshold" (user-reported:
rejection reasons were shown as a bare code with no number to back it up).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rejected_jobs", sa.Column("experience_years_min", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("rejected_jobs", "experience_years_min")
