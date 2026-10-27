from unittest.mock import Mock, patch

from fretflow.worker import main


def test_worker_dispatches_separation_with_configured_owner():
    pipeline = Mock()
    with patch("fretflow.worker.Settings.from_env") as from_env, patch(
        "fretflow.worker.create_pipeline", return_value=pipeline
    ):
        from_env.return_value.owner_id = "local-user"
        assert main(["separation", "job-1"]) == 0
    pipeline.run_separation.assert_called_once_with("local-user", "job-1")


def test_worker_dispatches_tab_with_explicit_owner():
    pipeline = Mock()
    with patch("fretflow.worker.Settings.from_env") as from_env, patch(
        "fretflow.worker.create_pipeline", return_value=pipeline
    ):
        from_env.return_value.owner_id = "local-user"
        assert main(["tab", "tab-1", "--owner-id", "owner-2"]) == 0
    pipeline.run_tab.assert_called_once_with("owner-2", "tab-1")


def test_worker_returns_failure_for_pipeline_errors(capsys):
    with patch("fretflow.worker.Settings.from_env", side_effect=RuntimeError("boom")):
        assert main(["separation", "job-1"]) == 1
    assert "boom" in capsys.readouterr().err
