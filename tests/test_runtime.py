from pathlib import Path

import pytest

from fretflow.config import ConfigurationError, InferenceMode, Settings
from fretflow.runtime import create_pipeline


def settings(tmp_path: Path, fixture_dir: Path | None) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'runtime.sqlite'}",
        artifact_root=tmp_path / "artifacts",
        inference_mode=InferenceMode.FIXTURE,
        fixture_dir=fixture_dir,
        owner_id="local-user",
    )


def test_runtime_builds_fixture_pipeline_without_loading_models(tmp_path: Path):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "demo.mid").write_bytes(b"MThd")
    (fixtures / "demo.tab.json").write_text('{"events": []}', encoding="utf-8")

    pipeline = create_pipeline(settings(tmp_path, fixtures))

    assert pipeline is not None
    assert (tmp_path / "artifacts").is_dir()


def test_runtime_rejects_missing_fixtures_and_unconfigured_real_mode(tmp_path: Path):
    with pytest.raises(ConfigurationError, match="FRETFLOW_FIXTURE_DIR"):
        create_pipeline(settings(tmp_path, None))

    real = settings(tmp_path, tmp_path)
    real = Settings(
        database_url=real.database_url,
        artifact_root=real.artifact_root,
        inference_mode=InferenceMode.REAL,
        fixture_dir=real.fixture_dir,
        owner_id=real.owner_id,
    )
    with pytest.raises(ConfigurationError, match="GPU worker"):
        create_pipeline(real)
