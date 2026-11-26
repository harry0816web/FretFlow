"""Subprocess adapter for the MVSep inference CLI (CUDA, Apple MPS, or CPU)."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fretflow.domain import StemType
from fretflow.progress import ProgressCallback, report_progress
from fretflow.services.contracts import SeparationResult

PROGRESS_PREFIX = "FRETFLOW_PROGRESS "
OUTPUT_TAIL_LINES = 12

# Job percentage for each phase the inference script reports. Separation
# chunks are spread between the "separating" start and "writing".
PHASE_PERCENT = {
    "loading-model": 12,
    "decoding": 20,
    "separating": 22,
    "writing": 88,
}
SEPARATING_END_PERCENT = 87

# Runs a command, calls on_line for each output line, returns the exit code.
Executor = Callable[[list[str], Callable[[str], None]], int]


def stream_process(command: list[str], on_line: Callable[[str], None]) -> int:
    """Run a command with stderr merged into stdout, delivering lines live."""

    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            on_line(line.rstrip("\n"))
        return process.wait()


def progress_percent(event: dict[str, Any]) -> int | None:
    """Map one inference progress event to an overall job percentage."""

    phase = event.get("phase")
    if phase == "separating":
        total = int(event.get("total") or 0)
        done = int(event.get("done") or 0)
        if total <= 0:
            return PHASE_PERCENT["separating"]
        start = PHASE_PERCENT["separating"]
        span = SEPARATING_END_PERCENT - start
        return start + round(span * min(done, total) / total)
    return PHASE_PERCENT.get(str(phase))


class SubprocessMVSepRunner:
    """Execute one isolated MVSep process so GPU memory is released per job.

    ``python_executable`` lets the worker run MVSep in a different environment,
    such as the macOS ``.venv-mvsep`` that holds the MPS-enabled PyTorch build.
    """

    def __init__(
        self,
        *,
        script_path: Path,
        model_dir: Path,
        skip_checksum: bool = False,
        device: str = "auto",
        python_executable: Path | None = None,
        executor: Executor = stream_process,
    ) -> None:
        self._script_path = script_path.expanduser().resolve()
        self._model_dir = model_dir.expanduser().resolve()
        self._skip_checksum = skip_checksum
        self._device = device
        self._python = str(python_executable) if python_executable else sys.executable
        self._executor = executor

    def __call__(
        self,
        input_path: Path,
        stems: tuple[StemType, ...],
        output_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> SeparationResult:
        if not self._script_path.is_file():
            raise FileNotFoundError(f"MVSep runner not found: {self._script_path}")
        destination = output_dir.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        command = [
            self._python,
            str(self._script_path),
            str(input_path),
            "--model-dir",
            str(self._model_dir),
            "--output-dir",
            str(destination),
            "--stems",
            *(stem.value for stem in stems),
            "--device",
            self._device,
            "--overwrite",
            "--progress-json",
        ]
        if self._skip_checksum:
            command.append("--skip-checksum")

        report_progress(progress, "starting", 10)
        tail: deque[str] = deque(maxlen=OUTPUT_TAIL_LINES)
        last_percent = 10

        def on_line(line: str) -> None:
            nonlocal last_percent
            # tqdm draws "\rSeparating: n%|..." on stderr without a newline, so
            # a progress record can land in the middle of a merged output line.
            marker = line.find(PROGRESS_PREFIX)
            if marker < 0:
                tail.append(line)
                return
            if marker > 0:
                tail.append(line[:marker])
            try:
                event = json.loads(line[marker + len(PROGRESS_PREFIX) :])
            except json.JSONDecodeError:
                return
            percent = progress_percent(event) if isinstance(event, dict) else None
            # Only write to the database when the visible number moves forward.
            if percent is not None and percent > last_percent:
                last_percent = percent
                report_progress(progress, str(event.get("phase")), percent)

        returncode = self._executor(command, on_line)
        if returncode != 0:
            detail = "\n".join(line for line in tail if line.strip()) or "unknown error"
            raise RuntimeError(f"MVSep process failed ({returncode}): {detail}")

        result_dir = destination / input_path.stem
        manifest_path = result_dir / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("MVSep process did not produce manifest.json")
        payload = self._read_manifest(manifest_path)
        report_progress(progress, "collecting-stems", 90)
        outputs = {
            StemType(output["stem"]): Path(output["path"])
            for output in payload.get("outputs", [])
            if isinstance(output, dict) and output.get("stem") and output.get("path")
        }
        inference = payload.get("inference", {})
        environment = payload.get("environment", {})
        diagnostics: dict[str, Any] = {
            "accelerator": {
                "backend": environment.get("accelerator_backend"),
                "device": environment.get("device"),
                "name": environment.get("gpu") or environment.get("cpu"),
            },
            "runtime": environment,
            "inference": inference,
        }
        return SeparationResult(
            manifest_path=manifest_path,
            stems=outputs,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Cannot read MVSep manifest: {error}") from error
        if not isinstance(payload, dict):
            raise RuntimeError("MVSep manifest must contain a JSON object")
        return payload
