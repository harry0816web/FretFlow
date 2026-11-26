import threading
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from fretflow.api import _create_default_services
from fretflow.config import InferenceMode, JobExecution, Settings
from fretflow.domain import JobStatus
from fretflow.repository import ClaimedJob
from fretflow.worker import run_claimed, serve
from tests.test_repository import (
    SEPARATION_ID,
    TAB_ID,
    repository,  # noqa: F401  (pytest fixture)
    seed_to_stem,
    separation,
    tab,
)


def test_queued_separation_is_claimed_exactly_once(repository):
    seed_to_stem(repository)

    claimed = repository.claim_next_job("mac-mps")

    assert claimed == ClaimedJob("separation", SEPARATION_ID, "local-user")
    job = repository.get_separation_job("local-user", SEPARATION_ID)
    assert job.status is JobStatus.RUNNING
    assert job.stage == "claimed"
    assert repository.claim_next_job("nvidia-gpu") is None


def test_tabs_are_claimed_after_separations_and_owner_scoped(repository):
    seed_to_stem(repository)
    repository.update_separation_job(
        replace(separation(), status=JobStatus.SUCCEEDED, stage="complete")
    )
    repository.create_tab(tab())

    assert repository.claim_tab("another-user", TAB_ID, "worker") is False
    assert repository.claim_next_job("worker") == ClaimedJob("tab", TAB_ID, "local-user")
    assert repository.claim_tab("local-user", TAB_ID, "worker") is False


def test_requeue_claimed_only_recovers_the_same_workers_jobs(repository):
    seed_to_stem(repository)
    repository.claim_next_job("mac-mps")

    assert repository.requeue_claimed("nvidia-gpu") == 0
    assert repository.requeue_claimed("mac-mps") == 1
    job = repository.get_separation_job("local-user", SEPARATION_ID)
    assert job.status is JobStatus.QUEUED
    assert repository.claim_next_job("nvidia-gpu").record_id == SEPARATION_ID


def test_failed_job_returns_to_the_queue_when_retried(repository):
    seed_to_stem(repository)
    repository.claim_next_job("worker")
    failed = replace(separation(), status=JobStatus.FAILED, stage="failed")
    repository.update_separation_job(failed)
    assert repository.claim_next_job("worker") is None

    repository.update_separation_job(replace(failed, status=JobStatus.QUEUED))

    assert repository.claim_next_job("worker").record_id == SEPARATION_ID


def test_run_claimed_dispatches_by_kind_and_reports_failures(capsys):
    pipeline = Mock()
    assert run_claimed(pipeline, ClaimedJob("separation", "job-1", "owner"))
    pipeline.run_separation.assert_called_once_with("owner", "job-1")
    assert run_claimed(pipeline, ClaimedJob("tab", "tab-1", "owner"))
    pipeline.run_tab.assert_called_once_with("owner", "tab-1")

    pipeline.run_tab.side_effect = RuntimeError("MPS out of memory")
    assert run_claimed(pipeline, ClaimedJob("tab", "tab-2", "owner")) is False
    assert "MPS out of memory" in capsys.readouterr().err


def test_serve_recovers_then_processes_queue_until_empty():
    queue = Mock()
    queue.requeue_claimed.return_value = 1
    stop = _stop_when_empty(
        queue,
        [
            ClaimedJob("separation", "job-1", "owner"),
            ClaimedJob("tab", "tab-1", "owner"),
            None,
        ],
    )
    pipeline = Mock()
    messages = []

    processed = serve(
        queue, pipeline, "mac-mps", poll_interval=0, once=False,
        stop=stop, log=messages.append,
    )

    assert processed == 2
    queue.requeue_claimed.assert_called_once_with("mac-mps")
    assert any("Requeued 1" in message for message in messages)


def test_serve_once_exits_on_an_empty_queue():
    queue = Mock()
    queue.requeue_claimed.return_value = 0
    queue.claim_next_job.return_value = None

    assert serve(queue, Mock(), "w", poll_interval=0, once=True, log=lambda _: None) == 0


def test_queue_mode_api_never_builds_an_inference_pipeline(tmp_path: Path):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'api.sqlite'}",
        artifact_root=tmp_path / "artifacts",
        inference_mode=InferenceMode.REAL,
        fixture_dir=None,
        owner_id="local-user",
        model_dir=tmp_path / "missing-model",
        job_execution=JobExecution.QUEUE,
    )

    services = _create_default_services(settings)

    assert services.pipeline is None
    assert services.execute_jobs is False


def _stop_when_empty(queue: Mock, jobs: list) -> threading.Event:
    stop = threading.Event()

    def claim(worker_id):
        job = jobs.pop(0)
        if job is None:
            stop.set()
        return job

    queue.claim_next_job.side_effect = claim
    return stop


def test_serve_survives_a_transient_queue_error():
    queue = Mock()
    queue.requeue_claimed.return_value = 0
    stop = threading.Event()
    calls = []

    def claim(worker_id):
        calls.append(worker_id)
        if len(calls) == 1:
            raise ConnectionError("database restarting")
        stop.set()
        return None

    queue.claim_next_job.side_effect = claim
    messages = []

    serve(queue, Mock(), "w", poll_interval=0, stop=_NoWaitEvent(stop), log=messages.append)

    assert len(calls) == 2
    assert any("retrying" in message for message in messages)


class _NoWaitEvent:
    """Event wrapper whose wait() returns immediately to keep the test fast."""

    def __init__(self, event: threading.Event) -> None:
        self._event = event

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, _timeout: float) -> bool:
        return self._event.is_set()
