"""Dependency-injection contracts for model-backed services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from fretflow.domain import StemType, TabOptions
from fretflow.progress import ProgressCallback


@dataclass(frozen=True, slots=True)
class SeparationResult:
    manifest_path: Path
    stems: dict[StemType, Path]
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TabTranscriptionResult:
    midi_path: Path
    tab_path: Path
    model_output_path: Path | None
    event_count: int
    dropped_note_count: int
    elapsed_seconds: float
    diagnostics: dict[str, Any] = field(default_factory=dict)


class StemSeparator(Protocol):
    def separate(
        self,
        input_path: Path,
        stems: tuple[StemType, ...],
        output_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> SeparationResult: ...


class TabTranscriber(Protocol):
    def transcribe(
        self,
        stem_path: Path,
        options: TabOptions,
        output_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> TabTranscriptionResult: ...
