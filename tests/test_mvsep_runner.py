import json
import subprocess
from pathlib import Path

import pytest

from fretflow.domain import StemType
from fretflow.services.mvsep_runner import SubprocessMVSepRunner


def test_subprocess_runner_maps_manifest_outputs_and_diagnostics(tmp_path: Path):
    script = tmp_path / "infer_mvsep_mega.py"
    script.touch()
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    source = tmp_path / "source.wav"
    source.touch()
    output = tmp_path / "output"
    calls = []

    def executor(command, **options):
        calls.append((command, options))
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
        return subprocess.CompletedProcess(command, 0, "ok", "")

    runner = SubprocessMVSepRunner(
        script_path=script,
        model_dir=model_dir,
        skip_checksum=True,
        executor=executor,
    )
    result = runner(
        source,
        (StemType.ACOUSTIC_GUITAR, StemType.ELECTRIC_GUITAR),
        output,
    )

    assert set(result.stems) == {
        StemType.ACOUSTIC_GUITAR,
        StemType.ELECTRIC_GUITAR,
    }
    assert result.diagnostics["inference"]["real_time_factor"] == 0.03
    assert "--skip-checksum" in calls[0][0]
    assert result.diagnostics["accelerator"] == {
        "backend": "cuda",
        "device": "cuda:0",
        "name": "RTX",
    }
    command = calls[0][0]
    assert command[command.index("--device") + 1] == "auto"
    assert calls[0][1] == {"check": False, "capture_output": True, "text": True}


def test_subprocess_runner_surfaces_process_errors(tmp_path: Path):
    script = tmp_path / "infer.py"
    script.touch()
    model_dir = tmp_path / "models"
    model_dir.mkdir()

    runner = SubprocessMVSepRunner(
        script_path=script,
        model_dir=model_dir,
        executor=lambda command, **options: subprocess.CompletedProcess(
            command, 2, "", "CUDA failed"
        ),
    )

    with pytest.raises(RuntimeError, match="CUDA failed"):
        runner(tmp_path / "input.wav", (StemType.ACOUSTIC_GUITAR,), tmp_path / "out")


def test_subprocess_runner_uses_configured_interpreter_and_device(tmp_path: Path):
    script = tmp_path / "infer.py"
    script.touch()
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    calls = []

    def executor(command, **options):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "stop")

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
