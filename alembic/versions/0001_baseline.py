"""Establish the initial Alembic revision.

Revision ID: 0001_baseline
Revises: None
"""

from typing import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reserve the baseline; domain tables arrive with the repository milestone."""


def downgrade() -> None:
    """Remove the baseline revision marker."""
