"""drop scraper_credentials.last_check_status/last_checked_at — the live
"test cookie" validity check was removed (2026-09-08): a separate browser
hit against LinkedIn just to test the cookie was extra, unmeasured account
activity. A bad cookie now surfaces as a real failure on the scrape run
itself instead.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("scraper_credentials", "last_check_status")
    op.drop_column("scraper_credentials", "last_checked_at")


def downgrade() -> None:
    op.add_column("scraper_credentials", sa.Column("last_check_status", sa.String(20), nullable=True))
    op.add_column("scraper_credentials", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
