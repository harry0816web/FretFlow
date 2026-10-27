"""Application service assembly for local and worker processes."""

from __future__ import annotations

from pathlib import Path

from fretflow.artifacts import LocalArtifactStore
from fretflow.config import ConfigurationError, InferenceMode, Settings
from fretflow.database import create_database_engine, create_session_factory
from fretflow.pipeline import Pipeline
from fretflow.repository import SqlAlchemyJobRepository
from fretflow.services.fixture import FixtureStemSeparator, FixtureTabTranscriber


def create_pipeline(settings: Settings) -> Pipeline:
    """Build the local pipeline without loading model runtimes eagerly."""

    if settings.inference_mode is not InferenceMode.FIXTURE:
        raise ConfigurationError(
            "real inference requires the GPU worker runtime, which is not configured yet"
        )
    if settings.fixture_dir is None or not settings.fixture_dir.is_dir():
        raise ConfigurationError("FRETFLOW_FIXTURE_DIR must point to a fixture directory")
    midi_fixture = _find_fixture(settings.fixture_dir, "demo.mid")
    tab_fixture = _find_fixture(settings.fixture_dir, "demo.tab.json")
    engine = create_database_engine(settings.database_url)
    repository = SqlAlchemyJobRepository(create_session_factory(engine))
    return Pipeline(
        repository=repository,
        artifacts=LocalArtifactStore(settings.artifact_root),
        separator=FixtureStemSeparator(),
        transcriber=FixtureTabTranscriber(
            midi_fixture=midi_fixture,
            tab_fixture=tab_fixture,
        ),
        work_root=settings.artifact_root.parent / "work",
    )


def _find_fixture(root: Path, filename: str) -> Path:
    matches = sorted(root.rglob(filename))
    if not matches:
        raise ConfigurationError(f"fixture file not found below {root}: {filename}")
    return matches[0]
