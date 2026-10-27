"""SQLAlchemy persistence models for the FretFlow music library."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from fretflow.database import Base


class SongRow(Base):
    __tablename__ = "songs"

    song_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    source_artifact_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_songs_owner_created", "owner_id", "created_at"),
        UniqueConstraint(
            "owner_id", "source_artifact_key", name="uq_songs_owner_source_key"
        ),
    )


class SeparationJobRow(Base):
    __tablename__ = "separation_jobs"

    job_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    song_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("songs.song_id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_stems: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    auto_tab_stems: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(255))
    container_digest: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    elapsed_seconds: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        Index("ix_separation_jobs_owner_song", "owner_id", "song_id"),
        Index("ix_separation_jobs_status", "status"),
    )


class StemRow(Base):
    __tablename__ = "stems"

    stem_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    song_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("songs.song_id", ondelete="CASCADE"), nullable=False
    )
    separation_job_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("separation_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stem_type: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    tab_eligible: Mapped[bool] = mapped_column(nullable=False)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[int | None] = mapped_column(Integer)
    frames: Mapped[int | None] = mapped_column(BigInteger)
    subtype: Mapped[str | None] = mapped_column(String(64))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    peak: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "separation_job_id", "stem_type", name="uq_stems_job_type"
        ),
        UniqueConstraint("artifact_key", name="uq_stems_artifact_key"),
        Index("ix_stems_owner_song", "owner_id", "song_id"),
    )


class TabRow(Base):
    __tablename__ = "tabs"

    tab_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    job_id: Mapped[UUID] = mapped_column(Uuid, unique=True, nullable=False)
    song_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("songs.song_id", ondelete="CASCADE"), nullable=False
    )
    stem_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("stems.stem_id", ondelete="CASCADE"), nullable=False
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    options_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    midi_artifact_key: Mapped[str | None] = mapped_column(String(1024))
    tab_artifact_key: Mapped[str | None] = mapped_column(String(1024))
    model_output_artifact_key: Mapped[str | None] = mapped_column(String(1024))
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dropped_note_count: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    elapsed_seconds: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("stem_id", "options_hash", name="uq_tabs_stem_options"),
        Index("ix_tabs_owner_song", "owner_id", "song_id"),
        Index("ix_tabs_status", "status"),
    )
