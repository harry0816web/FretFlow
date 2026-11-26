import json
import subprocess
from pathlib import Path

import pytest

from fretflow.domain import StemType
import sys

from fretflow.services.mvsep_runner import (
    SubprocessMVSepRunner,
    progress_percent,
    stream_process,
)


def test_subprocess_runner_maps_manifest_outputs_and_diagnostics(tmp_path: Path):
    script = tmp_path / "infer_mvsep_mega.py"
    script.touch()
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    source = tmp_path / "source.wav"
    source.touch()
    output = tmp_path / "output"
    calls = []

    def executor(command, on_line):
        calls.append(command)
        on_line("Loading model")
        on_line('FRETFLOW_PROGRESS {"phase": "loading-model", "done": 0, "total": 0}')
        for done in range(1, 5):
            on_line(
                'FRETFLOW_PROGRESS {"phase": "separating", "done": %d, "total": 4}' % done
            )
        on_line("FRETFLOW_PROGRESS not-json")
        result_dir = output / "source"
        result_dir.mkdir(parents=True)
        acoustic = result_dir / "acoustic-guitar.wav"
        electric = result_dir / "electric-guitar.wav"
        acoustic.touch()
        electric.touch()
        (result_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "environment": {
                        "gpu": "RTX",
                        "device": "cuda:0",
                        "accelerator_backend": "cuda",
                    },
                    "inference": {"real_time_factor": 0.03},
                    "outputs": [
                        {"stem": "acoustic-guitar", "path": str(acoustic)},
                        {"stem": "electric-guitar", "path": str(electric)},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return 0

    runner = SubprocessMVSepRunner(
        script_path=script,
        model_dir=model_dir,
        skip_checksum=True,
        executor=executor,
    )
    events = []
    result = runner(
        source,
        (StemType.ACOUSTIC_GUITAR, StemType.ELECTRIC_GUITAR),
        output,
        events.append,
    )

    assert set(result.stems) == {
        StemType.ACOUSTIC_GUITAR,
        StemType.ELECTRIC_GUITAR,
    }
    assert result.diagnostics["inference"]["real_time_factor"] == 0.03
    assert "--skip-checksum" in calls[0]
    assert "--progress-json" in calls[0]
    percents = [event.progress_percent for event in events]
    assert percents == sorted(percents)
    assert percents[:3] == [10, 12, 38]
    assert 87 in percents and percents[-1] == 90
    assert result.diagnostics["accelerator"] == {
        "backend": "cuda",
        "device": "cuda:0",
        "name": "RTX",
    }
    command = calls[0]
    assert command[command.index("--device") + 1] == "auto"


def test_subprocess_runner_surfaces_process_errors(tmp_path: Path):
    script = tmp_path / "infer.py"
    script.touch()
    model_dir = tmp_path / "models"
    model_dir.mkdir()

    runner = SubprocessMVSepRunner(
        script_path=script,
        model_dir=model_dir,
        executor=lambda command, on_line: (on_line("Traceback ..."), on_line("CUDA failed"), 2)[-1],
    )

    with pytest.raises(RuntimeError, match="CUDA failed"):
        runner(tmp_path / "input.wav", (StemType.ACOUSTIC_GUITAR,), tmp_path / "out")


def test_subprocess_runner_uses_configured_interpreter_and_device(tmp_path: Path):
    script = tmp_path / "infer.py"
    script.touch()
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    calls = []

    def executor(command, on_line):
        calls.append(command)
        on_line("stop")
        return 1

    runner = SubprocessMVSepRunner(
        script_path=script,
        model_dir=model_dir,
        device="mps",
        python_executable=Path("/venv-mvsep/bin/python"),
        executor=executor,
    )
    with pytest.raises(RuntimeError, match="stop"):
        runner(tmp_path / "input.wav", (StemType.BASS,), tmp_path / "out")

    assert calls[0][0] == "/venv-mvsep/bin/python"
    assert calls[0][calls[0].index("--device") + 1] == "mps"


def test_progress_percent_maps_phases_and_clamps_chunks():
    assert progress_percent({"phase": "loading-model"}) == 12
    assert progress_percent({"phase": "separating", "done": 0, "total": 10}) == 22
    assert progress_percent({"phase": "separating", "done": 5, "total": 10}) == 54
    assert progress_percent({"phase": "separating", "done": 99, "total": 10}) == 87
    assert progress_percent({"phase": "separating", "done": 1, "total": 0}) == 22
    assert progress_percent({"phase": "writing"}) == 88
    assert progress_percent({"phase": "mystery"}) is None


def test_stream_process_delivers_lines_live_and_returns_exit_code():
    lines = []
    code = stream_process(
        [sys.executable, "-c", "import sys; print('a'); print('b', file=sys.stderr); sys.exit(3)"],
        lines.append,
    )
    assert code == 3
    assert sorted(lines) == ["a", "b"]


def test_runner_finds_progress_records_glued_to_tqdm_output(tmp_path: Path):
    """Regression: tqdm's carriage-return bar shares the merged output stream."""

    script = tmp_path / "fake_infer.py"
    script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "out = Path(args[args.index('--output-dir') + 1]) / Path(args[0]).stem\n"
        "out.mkdir(parents=True)\n"
        "for i in range(1, 5):\n"
        "    sys.stderr.write(f'\\rSeparating: {i * 25}%|##| {i}/4'); sys.stderr.flush()\n"
        "    print('FRETFLOW_PROGRESS ' + json.dumps({'phase': 'separating', 'done': i, 'total': 4}), flush=True)\n"
        "(out / 'bass.wav').write_bytes(b'RIFF')\n"
        "(out / 'manifest.json').write_text(json.dumps({'outputs': [{'stem': 'bass', 'path': str(out / 'bass.wav')}]}))\n",
        encoding="utf-8",
    )
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    source = tmp_path / "song.wav"
    source.touch()
    events = []

    SubprocessMVSepRunner(script_path=script, model_dir=model_dir)(
        source, (StemType.BASS,), tmp_path / "out", events.append
    )

    separating = [e.progress_percent for e in events if e.stage == "separating"]
    assert separating == [38, 54, 71, 87]
