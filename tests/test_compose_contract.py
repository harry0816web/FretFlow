import os
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI is unavailable")
def test_compose_configuration_is_valid_and_app_waits_for_database_health():
    completed = subprocess.run(
        ["docker", "compose", "config"],
        check=True,
        env={**os.environ, "POSTGRES_PASSWORD": "compose-contract-test"},
        capture_output=True,
        text=True,
    )
    rendered = completed.stdout
    assert "condition: service_healthy" in rendered
    assert "127.0.0.1" in rendered


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI is unavailable")
def test_compose_refuses_to_start_without_a_database_password(tmp_path):
    environment = {key: value for key, value in os.environ.items() if key != "POSTGRES_PASSWORD"}
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("", encoding="utf-8")
    completed = subprocess.run(
        ["docker", "compose", "--env-file", str(empty_env), "config"],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode != 0
    assert "POSTGRES_PASSWORD" in completed.stderr


def test_repository_files_contain_no_default_database_password():
    import re

    for name in ("compose.yaml", "fretflow.sh"):
        text = open(name, encoding="utf-8").read()
        assert not re.search(r"POSTGRES_PASSWORD:-[^}]", text), name
