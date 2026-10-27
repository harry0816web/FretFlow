import json
from pathlib import Path

import pytest

from fretflow.domain import StemType, TabOptions
from fretflow.services.fixture import FixtureStemSeparator, FixtureTabTranscriber


def test_fixture_separator_copies_requested_stems_and_writes_manifest(tmp_path: Path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source-audio")
    guitar = tmp_path / "guitar.wav"
    guitar.write_bytes(b"guitar-audio")
    progress = []

    result = FixtureStemSeparator(
        {StemType.ACOUSTIC_GUITAR: guitar}
    ).separate(
        source,
        (StemType.ACOUSTIC_GUITAR, StemType.DRUMS),
        tmp_path / "output",
        progress.append,
    )

    assert result.stems[StemType.ACOUSTIC_GUITAR].read_bytes() == b"guitar-audio"
    assert result.stems[StemType.DRUMS].read_bytes() == b"source-audio"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert [item["stem"] for item in manifest["outputs"]] == [
        "acoustic-guitar",
        "drums",
    ]
    assert progress[-1].progress_percent == 100


def test_fixture_separator_fails_before_partial_output_for_missing_fixture(
    tmp_path: Path,
):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    destination = tmp_path / "output"

    with pytest.raises(FileNotFoundError):
        FixtureStemSeparator(
            {StemType.VOCAL: tmp_path / "missing.wav"}
        ).separate(source, (StemType.VOCAL,), destination)
    assert not destination.exists() or list(destination.iterdir()) == []


def test_fixture_tab_transcriber_copies_artifacts_and_reads_diagnostics(
    tmp_path: Path,
):
    stem = tmp_path / "guitar.wav"
    stem.write_bytes(b"audio")
    midi = tmp_path / "demo.mid"
    midi.write_bytes(b"MThd")
    tab = tmp_path / "demo.tab.json"
    tab.write_text(
        json.dumps(
            {
                "events": [{"onset_seconds": 0.1, "notes": []}],
                "diagnostics": {"dropped_note_assignments": 2},
            }
        ),
        encoding="utf-8",
    )
    model = tmp_path / "model.npz"
    model.write_bytes(b"npz")

    result = FixtureTabTranscriber(
        midi_fixture=midi,
        tab_fixture=tab,
        model_output_fixture=model,
    ).transcribe(stem, TabOptions(tuning="drop-d"), tmp_path / "output")

    assert result.midi_path.read_bytes() == b"MThd"
    assert result.model_output_path is not None
    assert result.model_output_path.read_bytes() == b"npz"
    assert result.event_count == 1
    assert result.dropped_note_count == 2
    assert result.diagnostics["tuning"] == "drop-d"


def test_fixture_tab_transcriber_rejects_missing_fixture_before_copy(tmp_path: Path):
    stem = tmp_path / "guitar.wav"
    stem.write_bytes(b"audio")
    service = FixtureTabTranscriber(
        midi_fixture=tmp_path / "missing.mid",
        tab_fixture=tmp_path / "missing.json",
    )
    with pytest.raises(FileNotFoundError):
        service.transcribe(stem, TabOptions(), tmp_path / "output")
