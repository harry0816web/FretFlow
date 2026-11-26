"""Add queue columns so a separate worker process can claim jobs.

Revision ID: 0003_job_queue
Revises: 0002_library_schema
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_job_queue"
down_revision: str | None = "0002_library_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("separation_jobs", "tabs")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(
            table, sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column(table, sa.Column("claimed_by", sa.String(255), nullable=True))
        op.create_index(f"ix_{table}_status_queued", table, ["status", "queued_at"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_status_queued", table_name=table)
        op.drop_column(table, "claimed_by")
        op.drop_column(table, "queued_at")
