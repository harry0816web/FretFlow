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


def test_runtime_rejects_missing_fixtures_and_missing_real_assets(tmp_path: Path):
    with pytest.raises(ConfigurationError, match="FRETFLOW_FIXTURE_DIR"):
        create_pipeline(settings(tmp_path, None))

    real = settings(tmp_path, tmp_path)
    real = Settings(
        database_url=real.database_url,
        artifact_root=real.artifact_root,
        inference_mode=InferenceMode.REAL,
        fixture_dir=real.fixture_dir,
        owner_id=real.owner_id,
        model_dir=tmp_path / "missing-model",
    )
    with pytest.raises(ConfigurationError, match="FRETFLOW_MODEL_DIR"):
        create_pipeline(real)


def test_runtime_builds_real_pipeline_without_eager_model_loading(tmp_path: Path):
    script = tmp_path / "infer_mvsep_mega.py"
    script.touch()
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    real = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'real.sqlite'}",
        artifact_root=tmp_path / "artifacts",
        inference_mode=InferenceMode.REAL,
        fixture_dir=None,
        owner_id="local-user",
        model_dir=model_dir,
        mvsep_script=script,
        skip_model_checksum=True,
    )

    assert create_pipeline(real) is not None
