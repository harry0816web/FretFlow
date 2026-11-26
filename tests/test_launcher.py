import os
import shutil
import subprocess
from pathlib import Path

import pytest

LAUNCHER = Path("fretflow.sh").resolve()


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _detect(tmp_path: Path, *, system: str, machine: str, nvidia: bool) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(
        bin_dir,
        "uname",
        f'case "$1" in -s) echo {system};; -m) echo {machine};; *) echo {system};; esac',
    )
    if nvidia:
        _stub(bin_dir, "nvidia-smi", 'echo "GPU 0: NVIDIA GeForce RTX 5090"')
    for tool in ("bash", "dirname", "cat", "grep", "sed"):
        found = shutil.which(tool)
        if found:
            os.symlink(found, bin_dir / tool)
    completed = subprocess.run(
        ["bash", str(LAUNCHER), "detect"],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": str(bin_dir), "HOME": str(tmp_path)},
    )
    return completed.stdout.strip()


@pytest.mark.parametrize(
    ("system", "machine", "nvidia", "expected"),
    [
        ("Darwin", "arm64", False, "mac"),
        ("Linux", "x86_64", True, "nvidia"),
        ("Linux", "x86_64", False, "cpu"),
        ("Linux", "aarch64", False, "cpu"),
        ("Darwin", "x86_64", False, "cpu"),
    ],
)
def test_launcher_detects_accelerator(tmp_path, system, machine, nvidia, expected):
    assert _detect(tmp_path, system=system, machine=machine, nvidia=nvidia) == expected


def test_launcher_never_deletes_volumes():
    script = LAUNCHER.read_text(encoding="utf-8")
    assert "down -v" not in script
    assert "--volumes" not in script
