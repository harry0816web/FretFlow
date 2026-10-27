"""Deterministic inference adapters for local development and CI."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from fretflow.domain import StemType, TabOptions, normalize_stems
from fretflow.progress import ProgressCallback, report_progress
from fretflow.services.contracts import SeparationResult, TabTranscriptionResult


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as output:
            shutil.copyfileobj(source_handle, output)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic(destination: Path, payload: dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.part")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FixtureStemSeparator:
    """Copy configured fixture stems, falling back to the input for CI flows."""

    def __init__(
        self, stem_fixtures: Mapping[StemType, Path] | None = None
    ) -> None:
        self._fixtures = dict(stem_fixtures or {})

    def separate(
        self,
        input_path: Path,
        stems: tuple[StemType, ...],
        output_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> SeparationResult:
        source = input_path.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"fixture input does not exist: {source}")
        selected = normalize_stems(stems)
        destination = output_dir.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        manifest_path = destination / "manifest.json"
        expected_sources = {
            stem: self._fixtures.get(stem, source).expanduser().resolve()
            for stem in selected
        }
        missing = [path for path in expected_sources.values() if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"fixture stem does not exist: {missing[0]}")

        report_progress(progress, "fixture-separating", 25)
        outputs: dict[StemType, Path] = {}
        output_metadata = []
        for index, stem in enumerate(selected, start=1):
            fixture = expected_sources[stem]
            suffix = fixture.suffix.lower() or ".wav"
            output_path = destination / f"{stem.value}{suffix}"
            if output_path.exists():
                raise FileExistsError(f"fixture output already exists: {output_path}")
            _copy_atomic(fixture, output_path)
            outputs[stem] = output_path
            output_metadata.append(
                {
                    "stem": stem.value,
                    "path": str(output_path),
                    "size_bytes": output_path.stat().st_size,
                    "sha256": _sha256(output_path),
                }
            )
            report_progress(
                progress,
                "fixture-separating",
                25 + round(60 * index / len(selected)),
            )
        _write_json_atomic(
            manifest_path,
            {
                "schema_version": 1,
                "mode": "fixture",
                "input": {"path": str(source), "sha256": _sha256(source)},
                "outputs": output_metadata,
            },
        )
        report_progress(progress, "complete", 100)
        return SeparationResult(
            manifest_path=manifest_path,
            stems=outputs,
            diagnostics={"mode": "fixture"},
        )


class FixtureTabTranscriber:
    def __init__(
        self,
        *,
        midi_fixture: Path,
        tab_fixture: Path,
        model_output_fixture: Path | None = None,
    ) -> None:
        self._midi_fixture = midi_fixture
        self._tab_fixture = tab_fixture
        self._model_output_fixture = model_output_fixture

    def transcribe(
        self,
        stem_path: Path,
        options: TabOptions,
        output_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> TabTranscriptionResult:
        source = stem_path.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"fixture stem does not exist: {source}")
        fixtures = [self._midi_fixture, self._tab_fixture]
        if self._model_output_fixture is not None:
            fixtures.append(self._model_output_fixture)
        resolved = [path.expanduser().resolve() for path in fixtures]
        missing = [path for path in resolved if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"fixture TAB artifact does not exist: {missing[0]}")

        destination = output_dir.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        midi_path = destination / "transcription.mid"
        tab_path = destination / "transcription.tab.json"
        model_output_path = (
            destination / "model-output.npz"
            if self._model_output_fixture is not None
            else None
        )
        final_paths = [midi_path, tab_path]
        if model_output_path is not None:
            final_paths.append(model_output_path)
        if any(path.exists() for path in final_paths):
            raise FileExistsError("fixture TAB output already exists")

        report_progress(progress, "fixture-transcribing", 30)
        _copy_atomic(resolved[0], midi_path)
        _copy_atomic(resolved[1], tab_path)
        if model_output_path is not None:
            _copy_atomic(resolved[2], model_output_path)
        report_progress(progress, "complete", 100)

        payload = json.loads(tab_path.read_text(encoding="utf-8"))
        events = payload.get("events", [])
        diagnostics = payload.get("diagnostics", {})
        return TabTranscriptionResult(
            midi_path=midi_path,
            tab_path=tab_path,
            model_output_path=model_output_path,
            event_count=len(events),
            dropped_note_count=int(diagnostics.get("dropped_note_assignments", 0)),
            elapsed_seconds=0.0,
            diagnostics={**diagnostics, "mode": "fixture", "tuning": options.tuning},
        )
