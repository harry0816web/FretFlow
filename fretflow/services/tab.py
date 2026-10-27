"""Basic Pitch and guitar-fretboard transcription service."""

from __future__ import annotations

import logging
import tempfile
import time
import warnings
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from basic_pitch_tab import TUNINGS, create_tab_events, midi_to_hz, write_outputs

from fretflow.domain import DomainValidationError, TabOptions
from fretflow.progress import ProgressCallback, report_progress
from fretflow.services.contracts import TabTranscriptionResult

Predictor = Callable[..., tuple[dict[str, Any], Any, list[Any]]]


def load_basic_pitch_predictor() -> tuple[Predictor, Path]:
    """Load Basic Pitch lazily so unit tests and API startup do not load its runtime."""

    previous_logging_disable = logging.root.manager.disable
    logging.disable(logging.WARNING)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="pkg_resources is deprecated as an API.*",
                category=UserWarning,
            )
            from basic_pitch import ICASSP_2022_MODEL_PATH
            from basic_pitch.inference import predict
    finally:
        logging.disable(previous_logging_disable)
    return predict, Path(ICASSP_2022_MODEL_PATH)


class BasicPitchTabService:
    def __init__(
        self,
        predictor: Predictor | None = None,
        model_path: Path | None = None,
    ) -> None:
        if (predictor is None) != (model_path is None):
            raise ValueError("predictor and model_path must be supplied together")
        self._predictor = predictor
        self._model_path = model_path

    def transcribe(
        self,
        stem_path: Path,
        options: TabOptions,
        output_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> TabTranscriptionResult:
        source = stem_path.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"guitar stem does not exist: {source}")
        if options.tuning not in TUNINGS:
            raise DomainValidationError(f"unsupported tuning: {options.tuning}")
        destination = output_dir.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        midi_path = destination / "transcription.mid"
        tab_path = destination / "transcription.tab.json"
        if midi_path.exists() or tab_path.exists():
            raise FileExistsError("TAB output already exists")

        report_progress(progress, "loading-model", 10)
        predictor, model_path = self._resolve_predictor()
        tuning = TUNINGS[options.tuning]
        report_progress(progress, "transcribing", 20)
        started = time.perf_counter()
        _, midi_data, note_events = predictor(
            source,
            model_or_model_path=model_path,
            onset_threshold=options.onset_threshold,
            frame_threshold=options.frame_threshold,
            minimum_note_length=options.minimum_note_length_ms,
            minimum_frequency=midi_to_hz(min(tuning) + options.capo),
            maximum_frequency=midi_to_hz(max(tuning) + options.max_fret),
            multiple_pitch_bends=True,
        )
        report_progress(progress, "optimizing-fretboard", 70)
        events, diagnostics = create_tab_events(
            note_events,
            tuning=tuning,
            max_fret=options.max_fret,
            capo=options.capo,
            onset_tolerance=options.onset_tolerance,
            max_stretch=options.max_stretch,
            candidate_limit=options.candidate_limit,
        )
        elapsed = time.perf_counter() - started
        report_progress(progress, "writing-artifacts", 90)
        args = SimpleNamespace(
            tuning=options.tuning,
            capo=options.capo,
            max_fret=options.max_fret,
            max_stretch=options.max_stretch,
            onset_tolerance=options.onset_tolerance,
            candidate_limit=options.candidate_limit,
            onset_threshold=options.onset_threshold,
            frame_threshold=options.frame_threshold,
            minimum_note_length=options.minimum_note_length_ms,
        )
        with tempfile.TemporaryDirectory(prefix=".tab-part-", dir=destination) as temp:
            temporary_dir = Path(temp)
            temporary_midi = temporary_dir / midi_path.name
            temporary_tab = temporary_dir / tab_path.name
            write_outputs(
                source,
                temporary_tab,
                temporary_midi,
                midi_data,
                note_events,
                events,
                diagnostics,
                args,
                tuning,
                model_path,
                elapsed,
            )
            temporary_midi.replace(midi_path)
            temporary_tab.replace(tab_path)
        report_progress(progress, "complete", 100)
        return TabTranscriptionResult(
            midi_path=midi_path,
            tab_path=tab_path,
            model_output_path=None,
            event_count=len(events),
            dropped_note_count=int(diagnostics["dropped_note_assignments"]),
            elapsed_seconds=elapsed,
            diagnostics=diagnostics,
        )

    def _resolve_predictor(self) -> tuple[Predictor, Path]:
        if self._predictor is None or self._model_path is None:
            self._predictor, self._model_path = load_basic_pitch_predictor()
        return self._predictor, self._model_path
