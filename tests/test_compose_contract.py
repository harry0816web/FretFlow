import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker CLI is unavailable")
def test_compose_configuration_is_valid_and_app_waits_for_database_health():
    completed = subprocess.run(
        ["docker", "compose", "config"],
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = completed.stdout
    assert "condition: service_healthy" in rendered
    assert "127.0.0.1" in rendered
