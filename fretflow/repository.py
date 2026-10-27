"""Owner-scoped persistence operations for songs, stems, and jobs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from fretflow.database import session_scope
from fretflow.domain import (
    ArtifactStatus,
    JobStatus,
    SeparationJob,
    Song,
    SongStatus,
    Stem,
    StemType,
    Tab,
    TabOptions,
    utc_now,
)
from fretflow.models import SeparationJobRow, SongRow, StemRow, TabRow


class RepositoryError(RuntimeError):
    pass


class RecordNotFoundError(RepositoryError):
    pass


class RepositoryConflictError(RepositoryError):
    pass


def tab_options_fingerprint(options: TabOptions) -> str:
    """Return a stable identifier for idempotent TAB requests."""

    payload = json.dumps(asdict(options), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class JobRepository(Protocol):
    def create_song(self, song: Song) -> Song: ...

    def get_song(self, owner_id: str, song_id: str) -> Song: ...

    def update_song(self, song: Song) -> Song: ...

    def list_songs(
        self,
        owner_id: str,
        *,
        search: str | None = None,
        status: SongStatus | None = None,
    ) -> list[Song]: ...

    def delete_song(self, owner_id: str, song_id: str) -> None: ...

    def create_separation_job(self, job: SeparationJob) -> SeparationJob: ...

    def get_separation_job(self, owner_id: str, job_id: str) -> SeparationJob: ...

    def update_separation_job(self, job: SeparationJob) -> SeparationJob: ...

    def create_stem(self, stem: Stem) -> Stem: ...

    def get_stem(self, owner_id: str, stem_id: str) -> Stem: ...

    def list_stems(self, owner_id: str, song_id: str) -> list[Stem]: ...

    def create_tab(self, tab: Tab) -> Tab: ...

    def get_tab(self, owner_id: str, tab_id: str) -> Tab: ...

    def update_tab(self, tab: Tab) -> Tab: ...

    def list_tabs(
        self, owner_id: str, *, status: JobStatus | None = None
    ) -> list[Tab]: ...


class SqlAlchemyJobRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def create_song(self, song: Song) -> Song:
        row = SongRow(
            song_id=UUID(song.song_id),
            owner_id=song.owner_id,
            title=song.title,
            source_filename=song.source_filename,
            source_artifact_key=song.source_artifact_key,
            duration_seconds=song.duration_seconds,
            media_type=song.media_type,
            sha256=song.sha256,
            status=song.status.value,
            created_at=song.created_at,
            updated_at=song.updated_at,
        )
        self._add(row)
        return song

    def get_song(self, owner_id: str, song_id: str) -> Song:
        with session_scope(self._factory) as session:
            row = session.scalar(
                select(SongRow).where(
                    SongRow.song_id == UUID(song_id), SongRow.owner_id == owner_id
                )
            )
            if row is None:
                raise RecordNotFoundError("song not found")
            return _song_from_row(row)

    def list_songs(
        self,
        owner_id: str,
        *,
        search: str | None = None,
        status: SongStatus | None = None,
    ) -> list[Song]:
        statement = select(SongRow).where(SongRow.owner_id == owner_id)
        if search and search.strip():
            statement = statement.where(SongRow.title.ilike(f"%{search.strip()}%"))
        if status is not None:
            statement = statement.where(SongRow.status == SongStatus(status).value)
        statement = statement.order_by(SongRow.created_at.desc())
        with session_scope(self._factory) as session:
            return [_song_from_row(row) for row in session.scalars(statement)]

    def update_song(self, song: Song) -> Song:
        with session_scope(self._factory) as session:
            row = _owned_row(session, SongRow, song.song_id, song.owner_id, "song")
            row.title = song.title
            row.duration_seconds = song.duration_seconds
            row.media_type = song.media_type
            row.sha256 = song.sha256
            row.status = song.status.value
            row.updated_at = song.updated_at
        return song

    def delete_song(self, owner_id: str, song_id: str) -> None:
        with session_scope(self._factory) as session:
            row = _owned_row(session, SongRow, song_id, owner_id, "song")
            session.delete(row)

    def create_separation_job(self, job: SeparationJob) -> SeparationJob:
        row = SeparationJobRow(
            job_id=UUID(job.job_id),
            song_id=UUID(job.song_id),
            owner_id=job.owner_id,
            requested_stems=[stem.value for stem in job.requested_stems],
            auto_tab_stems=[stem.value for stem in job.auto_tab_stems],
            status=job.status.value,
            stage=job.stage,
            progress_percent=job.progress_percent,
            model_version=job.model_version,
            container_digest=job.container_digest,
            started_at=job.started_at,
            finished_at=job.finished_at,
            elapsed_seconds=job.elapsed_seconds,
            error_code=job.error_code,
            error_message=job.error_message,
            diagnostics=dict(job.diagnostics),
        )
        self._add(row)
        return job

    def get_separation_job(self, owner_id: str, job_id: str) -> SeparationJob:
        with session_scope(self._factory) as session:
            row = session.scalar(
                select(SeparationJobRow).where(
                    SeparationJobRow.job_id == UUID(job_id),
                    SeparationJobRow.owner_id == owner_id,
                )
            )
            if row is None:
                raise RecordNotFoundError("separation job not found")
            return _separation_from_row(row)

    def update_separation_job(self, job: SeparationJob) -> SeparationJob:
        with session_scope(self._factory) as session:
            row = _owned_row(
                session, SeparationJobRow, job.job_id, job.owner_id, "separation job"
            )
            _assign_separation(row, job)
        return job

    def create_stem(self, stem: Stem) -> Stem:
        with session_scope(self._factory) as session:
            existing = session.scalar(
                select(StemRow).where(
                    StemRow.separation_job_id == UUID(stem.separation_job_id),
                    StemRow.stem_type == stem.stem_type.value,
                )
            )
            if existing is not None:
                if existing.owner_id != stem.owner_id:
                    raise RecordNotFoundError("stem not found")
                return _stem_from_row(existing)
            row = StemRow(
                stem_id=UUID(stem.stem_id),
                song_id=UUID(stem.song_id),
                separation_job_id=UUID(stem.separation_job_id),
                owner_id=stem.owner_id,
                stem_type=stem.stem_type.value,
                artifact_key=stem.artifact_key,
                status=stem.status.value,
                tab_eligible=stem.tab_eligible,
                sample_rate=stem.sample_rate,
                channels=stem.channels,
                frames=stem.frames,
                subtype=stem.subtype,
                duration_seconds=stem.duration_seconds,
                peak=stem.peak,
                created_at=utc_now(),
            )
            try:
                session.add(row)
                session.flush()
            except IntegrityError as error:
                raise RepositoryConflictError("stem already exists") from error
            return stem

    def get_stem(self, owner_id: str, stem_id: str) -> Stem:
        with session_scope(self._factory) as session:
            row = session.scalar(
                select(StemRow).where(
                    StemRow.stem_id == UUID(stem_id), StemRow.owner_id == owner_id
                )
            )
            if row is None:
                raise RecordNotFoundError("stem not found")
            return _stem_from_row(row)

    def list_stems(self, owner_id: str, song_id: str) -> list[Stem]:
        with session_scope(self._factory) as session:
            rows = session.scalars(
                select(StemRow)
                .where(
                    StemRow.owner_id == owner_id,
                    StemRow.song_id == UUID(song_id),
                )
                .order_by(StemRow.created_at, StemRow.stem_type)
            )
            return [_stem_from_row(row) for row in rows]

    def create_tab(self, tab: Tab) -> Tab:
        options_hash = tab_options_fingerprint(tab.options)
        with session_scope(self._factory) as session:
            existing = session.scalar(
                select(TabRow).where(
                    TabRow.stem_id == UUID(tab.stem_id),
                    TabRow.options_hash == options_hash,
                )
            )
            if existing is not None:
                if existing.owner_id != tab.owner_id:
                    raise RecordNotFoundError("TAB not found")
                return _tab_from_row(existing)
            row = _tab_row(tab, options_hash)
            try:
                session.add(row)
                session.flush()
            except IntegrityError as error:
                raise RepositoryConflictError("TAB already exists") from error
            return tab

    def get_tab(self, owner_id: str, tab_id: str) -> Tab:
        with session_scope(self._factory) as session:
            row = session.scalar(
                select(TabRow).where(
                    TabRow.tab_id == UUID(tab_id), TabRow.owner_id == owner_id
                )
            )
            if row is None:
                raise RecordNotFoundError("TAB not found")
            return _tab_from_row(row)

    def list_tabs(
        self, owner_id: str, *, status: JobStatus | None = None
    ) -> list[Tab]:
        statement = select(TabRow).where(TabRow.owner_id == owner_id)
        if status is not None:
            statement = statement.where(TabRow.status == JobStatus(status).value)
        statement = statement.order_by(TabRow.created_at.desc())
        with session_scope(self._factory) as session:
            return [_tab_from_row(row) for row in session.scalars(statement)]

    def update_tab(self, tab: Tab) -> Tab:
        with session_scope(self._factory) as session:
            row = _owned_row(session, TabRow, tab.tab_id, tab.owner_id, "TAB")
            row.job_id = UUID(tab.job_id)
            row.options = asdict(tab.options)
            row.options_hash = tab_options_fingerprint(tab.options)
            row.status = tab.status.value
            row.stage = tab.stage
            row.progress_percent = tab.progress_percent
            row.midi_artifact_key = tab.midi_artifact_key
            row.tab_artifact_key = tab.tab_artifact_key
            row.model_output_artifact_key = tab.model_output_artifact_key
            row.event_count = tab.event_count
            row.dropped_note_count = tab.dropped_note_count
            row.started_at = tab.started_at
            row.finished_at = tab.finished_at
            row.elapsed_seconds = tab.elapsed_seconds
            row.error_code = tab.error_code
            row.error_message = tab.error_message
            row.diagnostics = dict(tab.diagnostics)
        return tab

    def _add(self, row: object) -> None:
        try:
            with session_scope(self._factory) as session:
                session.add(row)
                session.flush()
        except IntegrityError as error:
            raise RepositoryConflictError("record already exists") from error


def _owned_row(
    session: Session,
    model: type[SongRow] | type[SeparationJobRow] | type[TabRow],
    record_id: str,
    owner_id: str,
    label: str,
) -> SongRow | SeparationJobRow | TabRow:
    row = session.get(model, UUID(record_id))
    if row is None or row.owner_id != owner_id:
        raise RecordNotFoundError(f"{label} not found")
    return row


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _song_from_row(row: SongRow) -> Song:
    return Song(
        song_id=str(row.song_id),
        owner_id=row.owner_id,
        title=row.title,
        source_filename=row.source_filename,
        source_artifact_key=row.source_artifact_key,
        duration_seconds=row.duration_seconds,
        media_type=row.media_type,
        sha256=row.sha256,
        status=SongStatus(row.status),
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


def _separation_from_row(row: SeparationJobRow) -> SeparationJob:
    return SeparationJob(
        job_id=str(row.job_id),
        song_id=str(row.song_id),
        owner_id=row.owner_id,
        requested_stems=tuple(StemType(value) for value in row.requested_stems),
        auto_tab_stems=tuple(StemType(value) for value in row.auto_tab_stems),
        status=JobStatus(row.status),
        stage=row.stage,
        progress_percent=row.progress_percent,
        model_version=row.model_version,
        container_digest=row.container_digest,
        started_at=_aware(row.started_at),
        finished_at=_aware(row.finished_at),
        elapsed_seconds=row.elapsed_seconds,
        error_code=row.error_code,
        error_message=row.error_message,
        diagnostics=dict(row.diagnostics),
    )


def _assign_separation(row: SeparationJobRow, job: SeparationJob) -> None:
    row.requested_stems = [stem.value for stem in job.requested_stems]
    row.auto_tab_stems = [stem.value for stem in job.auto_tab_stems]
    row.status = job.status.value
    row.stage = job.stage
    row.progress_percent = job.progress_percent
    row.model_version = job.model_version
    row.container_digest = job.container_digest
    row.started_at = job.started_at
    row.finished_at = job.finished_at
    row.elapsed_seconds = job.elapsed_seconds
    row.error_code = job.error_code
    row.error_message = job.error_message
    row.diagnostics = dict(job.diagnostics)


def _stem_from_row(row: StemRow) -> Stem:
    return Stem(
        stem_id=str(row.stem_id),
        song_id=str(row.song_id),
        separation_job_id=str(row.separation_job_id),
        owner_id=row.owner_id,
        stem_type=StemType(row.stem_type),
        artifact_key=row.artifact_key,
        status=ArtifactStatus(row.status),
        sample_rate=row.sample_rate,
        channels=row.channels,
        frames=row.frames,
        subtype=row.subtype,
        duration_seconds=row.duration_seconds,
        peak=row.peak,
    )


def _tab_row(tab: Tab, options_hash: str) -> TabRow:
    return TabRow(
        tab_id=UUID(tab.tab_id),
        job_id=UUID(tab.job_id),
        song_id=UUID(tab.song_id),
        stem_id=UUID(tab.stem_id),
        owner_id=tab.owner_id,
        options=asdict(tab.options),
        options_hash=options_hash,
        status=tab.status.value,
        stage=tab.stage,
        progress_percent=tab.progress_percent,
        midi_artifact_key=tab.midi_artifact_key,
        tab_artifact_key=tab.tab_artifact_key,
        model_output_artifact_key=tab.model_output_artifact_key,
        event_count=tab.event_count,
        dropped_note_count=tab.dropped_note_count,
        started_at=tab.started_at,
        finished_at=tab.finished_at,
        elapsed_seconds=tab.elapsed_seconds,
        error_code=tab.error_code,
        error_message=tab.error_message,
        diagnostics=dict(tab.diagnostics),
        created_at=utc_now(),
    )


def _tab_from_row(row: TabRow) -> Tab:
    return Tab(
        tab_id=str(row.tab_id),
        job_id=str(row.job_id),
        song_id=str(row.song_id),
        stem_id=str(row.stem_id),
        owner_id=row.owner_id,
        options=TabOptions(**row.options),
        status=JobStatus(row.status),
        stage=row.stage,
        progress_percent=row.progress_percent,
        midi_artifact_key=row.midi_artifact_key,
        tab_artifact_key=row.tab_artifact_key,
        model_output_artifact_key=row.model_output_artifact_key,
        event_count=row.event_count,
        dropped_note_count=row.dropped_note_count,
        started_at=_aware(row.started_at),
        finished_at=_aware(row.finished_at),
        elapsed_seconds=row.elapsed_seconds,
        error_code=row.error_code,
        error_message=row.error_message,
        diagnostics=dict(row.diagnostics),
    )
