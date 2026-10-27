"""Create the music library and job tables.

Revision ID: 0002_library_schema
Revises: 0001_baseline
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_library_schema"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "songs",
        sa.Column("song_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("source_filename", sa.String(length=500), nullable=False),
        sa.Column("source_artifact_key", sa.String(length=1024), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("song_id"),
        sa.UniqueConstraint(
            "owner_id", "source_artifact_key", name="uq_songs_owner_source_key"
        ),
    )
    op.create_index("ix_songs_owner_created", "songs", ["owner_id", "created_at"])
    op.create_table(
        "separation_jobs",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("song_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("requested_stems", sa.JSON(), nullable=False),
        sa.Column("auto_tab_stems", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("container_digest", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.song_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_separation_jobs_owner_song",
        "separation_jobs",
        ["owner_id", "song_id"],
    )
    op.create_index(
        "ix_separation_jobs_status", "separation_jobs", ["status"]
    )
    op.create_table(
        "stems",
        sa.Column("stem_id", sa.Uuid(), nullable=False),
        sa.Column("song_id", sa.Uuid(), nullable=False),
        sa.Column("separation_job_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("stem_type", sa.String(length=64), nullable=False),
        sa.Column("artifact_key", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tab_eligible", sa.Boolean(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("frames", sa.BigInteger(), nullable=True),
        sa.Column("subtype", sa.String(length=64), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("peak", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.song_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["separation_job_id"],
            ["separation_jobs.job_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("stem_id"),
        sa.UniqueConstraint("artifact_key", name="uq_stems_artifact_key"),
        sa.UniqueConstraint(
            "separation_job_id", "stem_type", name="uq_stems_job_type"
        ),
    )
    op.create_index("ix_stems_owner_song", "stems", ["owner_id", "song_id"])
    op.create_table(
        "tabs",
        sa.Column("tab_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("song_id", sa.Uuid(), nullable=False),
        sa.Column("stem_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("options_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("midi_artifact_key", sa.String(length=1024), nullable=True),
        sa.Column("tab_artifact_key", sa.String(length=1024), nullable=True),
        sa.Column("model_output_artifact_key", sa.String(length=1024), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("dropped_note_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_seconds", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["song_id"], ["songs.song_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stem_id"], ["stems.stem_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tab_id"),
        sa.UniqueConstraint("job_id"),
        sa.UniqueConstraint("stem_id", "options_hash", name="uq_tabs_stem_options"),
    )
    op.create_index("ix_tabs_owner_song", "tabs", ["owner_id", "song_id"])
    op.create_index("ix_tabs_status", "tabs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tabs_status", table_name="tabs")
    op.drop_index("ix_tabs_owner_song", table_name="tabs")
    op.drop_table("tabs")
    op.drop_index("ix_stems_owner_song", table_name="stems")
    op.drop_table("stems")
    op.drop_index("ix_separation_jobs_status", table_name="separation_jobs")
    op.drop_index("ix_separation_jobs_owner_song", table_name="separation_jobs")
    op.drop_table("separation_jobs")
    op.drop_index("ix_songs_owner_created", table_name="songs")
    op.drop_table("songs")
