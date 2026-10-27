"""Versioned artifact manifest schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from fretflow.domain import validate_artifact_key


class ManifestKind(str, Enum):
    SEPARATION = "separation"
    TAB = "tab"


class ManifestArtifact(BaseModel):
    key: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str | None = None

    @field_validator("key")
    @classmethod
    def key_must_be_safe(cls, value: str) -> str:
        return validate_artifact_key(value)


class ArtifactManifest(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    kind: ManifestKind
    owner_id: str = Field(min_length=1)
    song_id: UUID
    job_id: UUID
    created_at: datetime
    artifacts: list[ManifestArtifact] = Field(min_length=1)
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("owner_id")
    @classmethod
    def owner_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("owner_id must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def timestamp_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def artifact_keys_must_be_unique(self) -> "ArtifactManifest":
        keys = [artifact.key for artifact in self.artifacts]
        if len(keys) != len(set(keys)):
            raise ValueError("artifact keys must be unique")
        expected_prefix = f"songs/{self.song_id}/"
        if any(not key.startswith(expected_prefix) for key in keys):
            raise ValueError("artifact keys must belong to the manifest song")
        return self
