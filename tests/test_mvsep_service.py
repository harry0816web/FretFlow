from pathlib import Path

import pytest

from fretflow.domain import StemType
from fretflow.services.contracts import SeparationResult
from fretflow.services.mvsep import MVSepService


def test_mvsep_service_validates_and_returns_all_requested_stems(tmp_path: Path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    progress = []

    def runner(input_path, stems, output_dir, callback):
        assert input_path == source.resolve()
        assert stems == (StemType.DRUMS, StemType.ACOUSTIC_GUITAR)
        outputs = {}
        for stem in stems:
            path = output_dir / f"{stem.value}.wav"
            path.write_bytes(stem.value.encode())
            outputs[stem] = path
        manifest = output_dir / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        return SeparationResult(manifest_path=manifest, stems=outputs)

    result = MVSepService(runner).separate(
        source,
        (StemType.DRUMS, StemType.ACOUSTIC_GUITAR, StemType.DRUMS),
        tmp_path / "output",
        progress.append,
    )

    assert set(result.stems) == {StemType.DRUMS, StemType.ACOUSTIC_GUITAR}
    assert [event.progress_percent for event in progress] == [5, 100]


def test_mvsep_service_rejects_missing_input_before_calling_runner(tmp_path: Path):
    called = False

    def runner(*_args):
        nonlocal called
        called = True
        raise AssertionError("must not run")

    with pytest.raises(FileNotFoundError):
        MVSepService(runner).separate(
            tmp_path / "missing.wav",
            (StemType.DRUMS,),
            tmp_path / "output",
        )
    assert not called


def test_mvsep_service_rejects_incomplete_runner_output(tmp_path: Path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")

    def runner(_input_path, _stems, output_dir, _callback):
        manifest = output_dir / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        return SeparationResult(manifest_path=manifest, stems={})

    with pytest.raises(RuntimeError, match="every requested stem"):
        MVSepService(runner).separate(
            source,
            (StemType.VOCAL,),
            tmp_path / "output",
        )
