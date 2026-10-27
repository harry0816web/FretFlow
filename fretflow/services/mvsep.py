"""Validated adapter boundary for MVSep separation runners."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fretflow.domain import StemType, normalize_stems
from fretflow.progress import ProgressCallback, report_progress
from fretflow.services.contracts import SeparationResult

MVSepRunner = Callable[
    [Path, tuple[StemType, ...], Path, ProgressCallback | None], SeparationResult
]


class MVSepService:
    """Validate product rules around an injected, model-owning MVSep runner."""

    def __init__(self, runner: MVSepRunner) -> None:
        self._runner = runner

    def separate(
        self,
        input_path: Path,
        stems: tuple[StemType, ...],
        output_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> SeparationResult:
        source = input_path.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"audio input does not exist: {source}")
        selected = normalize_stems(stems)
        destination = output_dir.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        report_progress(progress, "preparing", 5)
        result = self._runner(source, selected, destination, progress)
        if set(result.stems) != set(selected):
            raise RuntimeError("MVSep runner did not return every requested stem")
        if not result.manifest_path.is_file():
            raise RuntimeError("MVSep runner did not produce a manifest")
        for stem, path in result.stems.items():
            if not path.is_file():
                raise RuntimeError(f"MVSep runner did not produce {stem.value}")
        report_progress(progress, "complete", 100)
        return result
