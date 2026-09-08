"""scraper_credentials — UI-editable per-site session credentials, no
restart needed (Phase 8: LI_AT_COOKIE was env-only before this)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scraper_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("site", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        # Set by check_scraper_credential_task (worker, Playwright) after a
        # "Test cookie" request — never inferred client-side, since only the
        # worker image has Playwright to actually ask LinkedIn.
        sa.Column("last_check_status", sa.String(20), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_scraper_credentials_site", "scraper_credentials", ["site"])


def downgrade() -> None:
    op.drop_table("scraper_credentials")
