"""Subprocess adapter for the CUDA MVSep inference CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fretflow.domain import StemType
from fretflow.progress import ProgressCallback, report_progress
from fretflow.services.contracts import SeparationResult

Executor = Callable[..., subprocess.CompletedProcess[str]]


class SubprocessMVSepRunner:
    """Execute one isolated MVSep process so CUDA memory is released per job."""

    def __init__(
        self,
        *,
        script_path: Path,
        model_dir: Path,
        skip_checksum: bool = False,
        executor: Executor = subprocess.run,
    ) -> None:
        self._script_path = script_path.expanduser().resolve()
        self._model_dir = model_dir.expanduser().resolve()
        self._skip_checksum = skip_checksum
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
            sys.executable,
            str(self._script_path),
            str(input_path),
            "--model-dir",
            str(self._model_dir),
            "--output-dir",
            str(destination),
            "--stems",
            *(stem.value for stem in stems),
            "--overwrite",
        ]
        if self._skip_checksum:
            command.append("--skip-checksum")

        report_progress(progress, "separating", 10)
        completed = self._executor(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            raise RuntimeError(f"MVSep process failed ({completed.returncode}): {detail}")

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
        diagnostics: dict[str, Any] = {
            "runtime": payload.get("environment", {}),
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
