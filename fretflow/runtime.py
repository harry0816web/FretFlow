"""Application service assembly for local and worker processes."""

from __future__ import annotations

from pathlib import Path

from fretflow.artifacts import LocalArtifactStore
from fretflow.config import ConfigurationError, InferenceMode, Settings
from fretflow.database import create_database_engine, create_session_factory
from fretflow.pipeline import Pipeline
from fretflow.repository import SqlAlchemyJobRepository
from fretflow.services.fixture import FixtureStemSeparator, FixtureTabTranscriber
from fretflow.services.mvsep import MVSepService
from fretflow.services.mvsep_runner import SubprocessMVSepRunner
from fretflow.services.tab import BasicPitchTabService


def create_pipeline(settings: Settings) -> Pipeline:
    """Build the local pipeline without loading model runtimes eagerly."""

    if settings.inference_mode is InferenceMode.FIXTURE:
        if settings.fixture_dir is None or not settings.fixture_dir.is_dir():
            raise ConfigurationError(
                "FRETFLOW_FIXTURE_DIR must point to a fixture directory"
            )
        midi_fixture = _find_fixture(settings.fixture_dir, "demo.mid")
        tab_fixture = _find_fixture(settings.fixture_dir, "demo.tab.json")
        separator = FixtureStemSeparator()
        transcriber = FixtureTabTranscriber(
            midi_fixture=midi_fixture,
            tab_fixture=tab_fixture,
        )
    else:
        if not settings.mvsep_script.is_file():
            raise ConfigurationError(
                f"FRETFLOW_MVSEP_SCRIPT does not exist: {settings.mvsep_script}"
            )
        if not settings.model_dir.is_dir():
            raise ConfigurationError(
                f"FRETFLOW_MODEL_DIR does not exist: {settings.model_dir}"
            )
        separator = MVSepService(
            SubprocessMVSepRunner(
                script_path=settings.mvsep_script,
                model_dir=settings.model_dir,
                skip_checksum=settings.skip_model_checksum,
                device=settings.device,
                python_executable=settings.mvsep_interpreter,
            )
        )
        transcriber = BasicPitchTabService()
    engine = create_database_engine(settings.database_url)
    repository = SqlAlchemyJobRepository(create_session_factory(engine))
    return Pipeline(
        repository=repository,
        artifacts=LocalArtifactStore(settings.artifact_root),
        separator=separator,
        transcriber=transcriber,
        work_root=settings.artifact_root.parent / "work",
        worker_id=settings.worker_id,
    )


def _find_fixture(root: Path, filename: str) -> Path:
    matches = sorted(root.rglob(filename))
    if not matches:
        raise ConfigurationError(f"fixture file not found below {root}: {filename}")
    return matches[0]
