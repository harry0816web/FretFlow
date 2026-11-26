import pytest

import sys
from pathlib import Path

from fretflow.config import ConfigurationError, InferenceMode, JobExecution, Settings


def test_settings_use_safe_local_defaults():
    settings = Settings.from_env({})
    assert settings.inference_mode is InferenceMode.FIXTURE
    assert settings.owner_id == "local-user"
    assert settings.fixture_dir is None
    assert settings.device == "auto"
    assert settings.job_execution is JobExecution.INLINE
    assert settings.mvsep_interpreter == Path(sys.executable)
    assert settings.worker_id


def test_settings_load_explicit_environment():
    settings = Settings.from_env(
        {
            "DATABASE_URL": "postgresql+psycopg://test:test@db/test",
            "INFERENCE_MODE": "real",
            "FRETFLOW_FIXTURE_DIR": "/fixtures",
            "FRETFLOW_LOCAL_OWNER_ID": "tester",
            "FRETFLOW_MODEL_DIR": "/models",
            "FRETFLOW_MVSEP_SCRIPT": "/app/infer_mvsep_mega.py",
            "FRETFLOW_SKIP_MODEL_CHECKSUM": "true",
            "FRETFLOW_DEVICE": "MPS",
            "FRETFLOW_MVSEP_PYTHON": "/venv/bin/python",
            "FRETFLOW_JOB_EXECUTION": "queue",
            "FRETFLOW_WORKER_ID": "mac-mps",
        }
    )
    assert settings.inference_mode is InferenceMode.REAL
    assert str(settings.fixture_dir) == "/fixtures"
    assert settings.owner_id == "tester"
    assert str(settings.model_dir) == "/models"
    assert str(settings.mvsep_script) == "/app/infer_mvsep_mega.py"
    assert settings.skip_model_checksum is True
    assert settings.device == "mps"
    assert settings.mvsep_interpreter == Path("/venv/bin/python")
    assert settings.job_execution is JobExecution.QUEUE
    assert settings.worker_id == "mac-mps"


def test_settings_accept_indexed_cuda_device():
    assert Settings.from_env({"FRETFLOW_DEVICE": "cuda:1"}).device == "cuda:1"


@pytest.mark.parametrize(
    "environment",
    [
        {"INFERENCE_MODE": "unknown"},
        {"DATABASE_URL": " "},
        {"FRETFLOW_LOCAL_OWNER_ID": " "},
        {"FRETFLOW_DEVICE": "vulkan"},
        {"FRETFLOW_JOB_EXECUTION": "celery"},
    ],
)
def test_settings_reject_invalid_environment(environment):
    with pytest.raises(ConfigurationError):
        Settings.from_env(environment)
