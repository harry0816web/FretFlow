"""Core domain values and validation shared by the API and workers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable
from uuid import UUID


class DomainValidationError(ValueError):
    """Raised when a value would violate a FretFlow domain rule."""


class StemType(str, Enum):
    ACOUSTIC_GUITAR = "acoustic-guitar"
    ELECTRIC_GUITAR = "electric-guitar"
    BASS = "bass"
    DRUMS = "drums"
    VOCAL = "vocal"

    @property
    def tab_eligible(self) -> bool:
        return self in TAB_ELIGIBLE_STEMS


TAB_ELIGIBLE_STEMS = frozenset(
    {StemType.ACOUSTIC_GUITAR, StemType.ELECTRIC_GUITAR}
)
DEFAULT_STEMS = (StemType.ACOUSTIC_GUITAR, StemType.ELECTRIC_GUITAR)


class SongStatus(str, Enum):
    UPLOADING = "UPLOADING"
    SEPARATING = "SEPARATING"
    READY = "READY"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ArtifactStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


JOB_STATUS_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
}


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def validate_artifact_key(value: str) -> str:
    """Validate a portable, relative artifact key used by local storage and S3."""

    if not value or value.startswith("/") or "\\" in value:
        raise DomainValidationError("artifact key must be a relative POSIX path")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise DomainValidationError("artifact key contains an unsafe path segment")
    return value


def validate_job_transition(
    current: JobStatus | str, target: JobStatus | str
) -> JobStatus:
    """Validate a normal job transition or an idempotent status update."""

    try:
        current_status = JobStatus(current)
        target_status = JobStatus(target)
    except ValueError as error:
        raise DomainValidationError("unknown job status") from error
    if current_status == target_status:
        return target_status
    if target_status not in JOB_STATUS_TRANSITIONS[current_status]:
        raise DomainValidationError(
            f"cannot transition job from {current_status.value} to {target_status.value}"
        )
    return target_status


def _validate_uuid(name: str, value: str) -> None:
    try:
        UUID(value)
    except (TypeError, ValueError, AttributeError) as error:
        raise DomainValidationError(f"{name} must be a UUID") from error


def _validate_text(name: str, value: str) -> None:
    if not value.strip():
        raise DomainValidationError(f"{name} must not be blank")


def _validate_timestamp(name: str, value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise DomainValidationError(f"{name} must include a timezone")


def _validate_sha256(value: str | None) -> None:
    if value is not None and re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise DomainValidationError("sha256 must be 64 lowercase hexadecimal characters")


def _validate_progress(value: int) -> None:
    if not 0 <= value <= 100:
        raise DomainValidationError("progress_percent must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class Song:
    song_id: str
    owner_id: str
    title: str
    source_filename: str
    source_artifact_key: str
    media_type: str
    duration_seconds: float | None = None
    sha256: str | None = None
    status: SongStatus = SongStatus.UPLOADING
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        _validate_uuid("song_id", self.song_id)
        for name, value in (
            ("owner_id", self.owner_id),
            ("title", self.title),
            ("source_filename", self.source_filename),
            ("media_type", self.media_type),
        ):
            _validate_text(name, value)
        validate_artifact_key(self.source_artifact_key)
        if not self.source_artifact_key.startswith(f"songs/{self.song_id}/source/"):
            raise DomainValidationError("source artifact key must belong to the song")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise DomainValidationError("duration_seconds must not be negative")
        _validate_sha256(self.sha256)
        try:
            object.__setattr__(self, "status", SongStatus(self.status))
        except ValueError as error:
            raise DomainValidationError("unknown song status") from error
        _validate_timestamp("created_at", self.created_at)
        _validate_timestamp("updated_at", self.updated_at)


@dataclass(frozen=True, slots=True)
class SeparationJob:
    job_id: str
    song_id: str
    owner_id: str
    requested_stems: tuple[StemType, ...]
    auto_tab_stems: tuple[StemType, ...] = ()
    status: JobStatus = JobStatus.QUEUED
    stage: str = "queued"
    progress_percent: int = 0
    model_version: str | None = None
    container_digest: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_seconds: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_uuid("job_id", self.job_id)
        _validate_uuid("song_id", self.song_id)
        _validate_text("owner_id", self.owner_id)
        _validate_text("stage", self.stage)
        requested = normalize_stems(self.requested_stems)
        automatic = (
            normalize_stems(self.auto_tab_stems) if self.auto_tab_stems else ()
        )
        if any(stem not in requested for stem in automatic):
            raise DomainValidationError("auto TAB stems must also be requested stems")
        if any(not stem.tab_eligible for stem in automatic):
            raise DomainValidationError("auto TAB stems must be guitar stems")
        object.__setattr__(self, "requested_stems", requested)
        object.__setattr__(self, "auto_tab_stems", automatic)
        try:
            object.__setattr__(self, "status", JobStatus(self.status))
        except ValueError as error:
            raise DomainValidationError("unknown job status") from error
        _validate_progress(self.progress_percent)
        for name, value in (
            ("started_at", self.started_at),
            ("finished_at", self.finished_at),
        ):
            _validate_timestamp(name, value)
        if self.elapsed_seconds is not None and self.elapsed_seconds < 0:
            raise DomainValidationError("elapsed_seconds must not be negative")


@dataclass(frozen=True, slots=True)
class Stem:
    stem_id: str
    song_id: str
    separation_job_id: str
    owner_id: str
    stem_type: StemType
    artifact_key: str
    status: ArtifactStatus = ArtifactStatus.PENDING
    sample_rate: int | None = None
    channels: int | None = None
    frames: int | None = None
    subtype: str | None = None
    duration_seconds: float | None = None
    peak: float | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("stem_id", self.stem_id),
            ("song_id", self.song_id),
            ("separation_job_id", self.separation_job_id),
        ):
            _validate_uuid(name, value)
        _validate_text("owner_id", self.owner_id)
        try:
            object.__setattr__(self, "stem_type", StemType(self.stem_type))
            object.__setattr__(self, "status", ArtifactStatus(self.status))
        except ValueError as error:
            raise DomainValidationError("unknown stem type or status") from error
        validate_artifact_key(self.artifact_key)
        expected_prefix = f"songs/{self.song_id}/separations/{self.separation_job_id}/stems/"
        if not self.artifact_key.startswith(expected_prefix):
            raise DomainValidationError("stem artifact key must belong to its separation")
        for name, value in (
            ("sample_rate", self.sample_rate),
            ("channels", self.channels),
            ("frames", self.frames),
        ):
            if value is not None and value <= 0:
                raise DomainValidationError(f"{name} must be positive")
        if self.duration_seconds is not None and self.duration_seconds < 0:
            raise DomainValidationError("duration_seconds must not be negative")
        if self.peak is not None and self.peak < 0:
            raise DomainValidationError("peak must not be negative")

    @property
    def tab_eligible(self) -> bool:
        return self.stem_type.tab_eligible


@dataclass(frozen=True, slots=True)
class Tab:
    tab_id: str
    job_id: str
    song_id: str
    stem_id: str
    owner_id: str
    options: "TabOptions"
    status: JobStatus = JobStatus.QUEUED
    stage: str = "queued"
    progress_percent: int = 0
    midi_artifact_key: str | None = None
    tab_artifact_key: str | None = None
    model_output_artifact_key: str | None = None
    event_count: int = 0
    dropped_note_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    elapsed_seconds: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("tab_id", self.tab_id),
            ("job_id", self.job_id),
            ("song_id", self.song_id),
            ("stem_id", self.stem_id),
        ):
            _validate_uuid(name, value)
        _validate_text("owner_id", self.owner_id)
        _validate_text("stage", self.stage)
        if not isinstance(self.options, TabOptions):
            raise DomainValidationError("options must be TabOptions")
        try:
            object.__setattr__(self, "status", JobStatus(self.status))
        except ValueError as error:
            raise DomainValidationError("unknown job status") from error
        _validate_progress(self.progress_percent)
        expected_prefix = f"songs/{self.song_id}/tabs/{self.tab_id}/"
        for name, value in (
            ("midi_artifact_key", self.midi_artifact_key),
            ("tab_artifact_key", self.tab_artifact_key),
            ("model_output_artifact_key", self.model_output_artifact_key),
        ):
            if value is not None:
                validate_artifact_key(value)
                if not value.startswith(expected_prefix):
                    raise DomainValidationError(f"{name} must belong to the TAB")
        if self.event_count < 0 or self.dropped_note_count < 0:
            raise DomainValidationError("TAB diagnostic counts must not be negative")
        for name, value in (
            ("started_at", self.started_at),
            ("finished_at", self.finished_at),
        ):
            _validate_timestamp(name, value)
        if self.elapsed_seconds is not None and self.elapsed_seconds < 0:
            raise DomainValidationError("elapsed_seconds must not be negative")


@dataclass(frozen=True, slots=True)
class TabOptions:
    tuning: str = "standard"
    capo: int = 0
    max_fret: int = 24
    max_stretch: int = 5
    onset_tolerance: float = 0.05
    candidate_limit: int = 64
    onset_threshold: float = 0.5
    frame_threshold: float = 0.3
    minimum_note_length_ms: float = 80.0

    def __post_init__(self) -> None:
        if not self.tuning.strip():
            raise DomainValidationError("tuning must not be blank")
        if not 0 <= self.capo <= 12:
            raise DomainValidationError("capo must be between 0 and 12")
        if not 12 <= self.max_fret <= 36:
            raise DomainValidationError("max_fret must be between 12 and 36")
        if not 1 <= self.max_stretch <= 12:
            raise DomainValidationError("max_stretch must be between 1 and 12")
        if not 0 < self.onset_tolerance <= 0.5:
            raise DomainValidationError("onset_tolerance must be between 0 and 0.5")
        if self.candidate_limit < 1:
            raise DomainValidationError("candidate_limit must be positive")
        if self.minimum_note_length_ms <= 0:
            raise DomainValidationError("minimum_note_length_ms must be positive")
        for name, value in (
            ("onset_threshold", self.onset_threshold),
            ("frame_threshold", self.frame_threshold),
        ):
            if not 0 < value < 1:
                raise DomainValidationError(f"{name} must be between 0 and 1")


def normalize_stems(values: Iterable[str | StemType]) -> tuple[StemType, ...]:
    """Validate, de-duplicate, and preserve the requested stem order."""

    result: list[StemType] = []
    for value in values:
        try:
            stem = value if isinstance(value, StemType) else StemType(value)
        except ValueError as error:
            raise DomainValidationError(f"unsupported stem type: {value}") from error
        if stem not in result:
            result.append(stem)
    if not result:
        raise DomainValidationError("at least one stem type is required")
    return tuple(result)


def select_auto_tab_stems(
    requested_stems: Iterable[str | StemType], enabled: bool
) -> tuple[StemType, ...]:
    """Return requested guitar stems eligible for the automatic TAB stage."""

    stems = normalize_stems(requested_stems)
    if not enabled:
        return ()
    return tuple(stem for stem in stems if stem.tab_eligible)
