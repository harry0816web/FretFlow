import json
from pathlib import Path

import pytest

from fretflow.domain import DomainValidationError, TabOptions
from fretflow.services.tab import BasicPitchTabService


class FakeMidi:
    def write(self, path: str) -> None:
        Path(path).write_bytes(b"MThd")


def test_tab_service_transcribes_with_an_injected_predictor(tmp_path: Path):
    source = tmp_path / "guitar.wav"
    source.write_bytes(b"audio")
    calls = []

    def predictor(path, **options):
        calls.append((path, options))
        return {}, FakeMidi(), [(0.1, 0.5, 64, 0.9, None)]

    progress = []
    result = BasicPitchTabService(predictor, Path("model.tflite")).transcribe(
        source,
        TabOptions(tuning="drop-d", capo=2, max_fret=24),
        tmp_path / "tab-output",
        progress.append,
    )

    assert result.midi_path.read_bytes() == b"MThd"
    payload = json.loads(result.tab_path.read_text(encoding="utf-8"))
    assert payload["tuning"]["name"] == "drop-d"
    assert payload["tuning"]["capo"] == 2
    assert result.event_count == 1
    assert calls[0][0] == source.resolve()
    assert calls[0][1]["multiple_pitch_bends"] is True
    assert [event.progress_percent for event in progress] == [10, 20, 70, 90, 100]


def test_tab_service_rejects_missing_input_and_unsupported_tuning(tmp_path: Path):
    service = BasicPitchTabService(lambda *_args, **_kwargs: None, Path("model"))
    with pytest.raises(FileNotFoundError):
        service.transcribe(
            tmp_path / "missing.wav", TabOptions(), tmp_path / "output"
        )

    source = tmp_path / "guitar.wav"
    source.write_bytes(b"audio")
    with pytest.raises(DomainValidationError, match="unsupported tuning"):
        service.transcribe(
            source, TabOptions(tuning="open-g"), tmp_path / "output"
        )


def test_tab_service_keeps_final_paths_clean_when_prediction_fails(tmp_path: Path):
    source = tmp_path / "guitar.wav"
    source.write_bytes(b"audio")
    destination = tmp_path / "output"

    def fail(*_args, **_kwargs):
        raise RuntimeError("model failure")

    with pytest.raises(RuntimeError, match="model failure"):
        BasicPitchTabService(fail, Path("model")).transcribe(
            source, TabOptions(), destination
        )
    assert not (destination / "transcription.mid").exists()
    assert not (destination / "transcription.tab.json").exists()


def test_tab_service_requires_predictor_and_model_path_as_a_pair():
    with pytest.raises(ValueError):
        BasicPitchTabService(lambda *_args, **_kwargs: None)
