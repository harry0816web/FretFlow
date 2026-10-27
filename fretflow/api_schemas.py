"""HTTP request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from fretflow.domain import StemType


class SongCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_filename: str = Field(min_length=1, max_length=500)
    media_type: str = Field(default="audio/mpeg", min_length=1, max_length=255)


class SongResponse(BaseModel):
    song_id: str
    title: str
    source_filename: str
    source_artifact_key: str
    duration_seconds: float | None
    media_type: str
    sha256: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    song_id: str
    artifact_key: str
    size_bytes: int


class SeparationCreateRequest(BaseModel):
    requested_stems: list[StemType] = Field(min_length=1)
    auto_tab: bool = False


class SeparationResponse(BaseModel):
    job_id: str
    song_id: str
    requested_stems: list[str]
    auto_tab_stems: list[str]
    status: str
    stage: str
    progress_percent: int
    started_at: datetime | None
    finished_at: datetime | None
    elapsed_seconds: float | None
    error_code: str | None
    error_message: str | None
    diagnostics: dict


class StemResponse(BaseModel):
    stem_id: str
    song_id: str
    separation_job_id: str
    stem_type: str
    status: str
    tab_eligible: bool
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None
    artifact_url: str


class TabCreateRequest(BaseModel):
    tuning: str = "standard"
    capo: int = 0
    max_fret: int = 24
    max_stretch: int = 5
    onset_tolerance: float = 0.05
    candidate_limit: int = 64
    onset_threshold: float = 0.5
    frame_threshold: float = 0.3
    minimum_note_length_ms: float = 80.0


class TabResponse(BaseModel):
    tab_id: str
    job_id: str
    song_id: str
    stem_id: str
    status: str
    stage: str
    progress_percent: int
    tuning: str
    capo: int
    max_fret: int
    max_stretch: int
    event_count: int
    dropped_note_count: int
    midi_url: str | None
    tab_url: str | None
    model_output_url: str | None
    started_at: datetime | None
    finished_at: datetime | None
    elapsed_seconds: float | None
    error_code: str | None
    error_message: str | None
