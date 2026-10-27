import pytest

from fretflow.config import ConfigurationError, InferenceMode, Settings


def test_settings_use_safe_local_defaults():
    settings = Settings.from_env({})
    assert settings.inference_mode is InferenceMode.FIXTURE
    assert settings.owner_id == "local-user"
    assert settings.fixture_dir is None


def test_settings_load_explicit_environment():
    settings = Settings.from_env(
        {
            "DATABASE_URL": "postgresql+psycopg://test:test@db/test",
            "INFERENCE_MODE": "real",
            "FRETFLOW_FIXTURE_DIR": "/fixtures",
            "FRETFLOW_LOCAL_OWNER_ID": "tester",
        }
    )
    assert settings.inference_mode is InferenceMode.REAL
    assert str(settings.fixture_dir) == "/fixtures"
    assert settings.owner_id == "tester"


@pytest.mark.parametrize(
    "environment",
    [
        {"INFERENCE_MODE": "unknown"},
        {"DATABASE_URL": " "},
        {"FRETFLOW_LOCAL_OWNER_ID": " "},
    ],
)
def test_settings_reject_invalid_environment(environment):
    with pytest.raises(ConfigurationError):
        Settings.from_env(environment)
