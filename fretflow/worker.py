"""Command-line worker: run one job, or serve the PostgreSQL job queue.

The API only enqueues jobs when ``FRETFLOW_JOB_EXECUTION=queue``. A worker on
the machine that owns the accelerator then claims and runs them:

* NVIDIA: the ``gpu-worker`` container (``--gpus all``) uses CUDA.
* Apple Silicon: a native macOS process uses MPS, because Docker on macOS
  cannot reach Metal.
* Anything else: the ``cpu-worker`` container falls back to CPU.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from collections.abc import Callable

from fretflow.config import Settings
from fretflow.database import create_database_engine, create_session_factory
from fretflow.pipeline import Pipeline
from fretflow.repository import ClaimedJob, JobQueue, SqlAlchemyJobRepository
from fretflow.runtime import create_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run FretFlow jobs")
    commands = parser.add_subparsers(dest="command", required=True)

    for job_type in ("separation", "tab"):
        single = commands.add_parser(job_type, help=f"Run one {job_type} job")
        single.add_argument("job_id")
        single.add_argument("--owner-id", default=None)

    serve = commands.add_parser("serve", help="Claim and run queued jobs")
    serve.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds to wait when the queue is empty (default: 2)",
    )
    serve.add_argument(
        "--once",
        action="store_true",
        help="Run at most one queued job, then exit",
    )
    return parser


def run_claimed(pipeline: Pipeline, job: ClaimedJob) -> bool:
    """Run one claimed job; failures are already recorded on the job row."""

    try:
        if job.kind == "separation":
            pipeline.run_separation(job.owner_id, job.record_id)
        else:
            pipeline.run_tab(job.owner_id, job.record_id)
        return True
    except Exception as error:
        print(f"FretFlow {job.kind} job {job.record_id} failed: {error}", file=sys.stderr)
        return False


def serve(
    queue: JobQueue,
    pipeline: Pipeline,
    worker_id: str,
    *,
    poll_interval: float,
    once: bool = False,
    stop: threading.Event | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Poll the queue until stopped; return the number of jobs processed."""

    stop = stop or threading.Event()
    recovered = queue.requeue_claimed(worker_id)
    if recovered:
        log(f"Requeued {recovered} job(s) left RUNNING by a previous {worker_id} run")
    log(f"FretFlow worker {worker_id} is waiting for jobs")
    processed = 0
    while not stop.is_set():
        try:
            job = queue.claim_next_job(worker_id)
        except Exception as error:  # e.g. PostgreSQL restarting
            log(f"Cannot reach the job queue ({error}); retrying")
            stop.wait(max(poll_interval, 1.0))
            continue
        if job is None:
            if once:
                break
            stop.wait(poll_interval)
            continue
        log(f"Running {job.kind} job {job.record_id}")
        succeeded = run_claimed(pipeline, job)
        processed += 1
        log(f"Finished {job.kind} job {job.record_id}: {'ok' if succeeded else 'failed'}")
        if once:
            break
    return processed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        pipeline = create_pipeline(settings)
        if args.command == "serve":
            stop = threading.Event()
            for signum in (signal.SIGINT, signal.SIGTERM):
                signal.signal(signum, lambda *_: stop.set())
            queue = SqlAlchemyJobRepository(
                create_session_factory(create_database_engine(settings.database_url))
            )
            serve(
                queue,
                pipeline,
                settings.worker_id,
                poll_interval=args.poll_interval,
                once=args.once,
                stop=stop,
                log=lambda message: print(message, flush=True),
            )
            return 0
        owner_id = args.owner_id or settings.owner_id
        if args.command == "separation":
            pipeline.run_separation(owner_id, args.job_id)
        else:
            pipeline.run_tab(owner_id, args.job_id)
        return 0
    except Exception as error:
        print(f"FretFlow worker failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
