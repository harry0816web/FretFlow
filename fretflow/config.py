"""Environment-backed application configuration."""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping


class ConfigurationError(ValueError):
    """Raised when environment configuration is invalid."""


class InferenceMode(str, Enum):
    FIXTURE = "fixture"
    REAL = "real"


class JobExecution(str, Enum):
    """Where queued jobs run: inside the API process, or in a separate worker."""

    INLINE = "inline"
    QUEUE = "queue"


DEVICE_CHOICES = ("auto", "cuda", "mps", "cpu")


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    artifact_root: Path
    inference_mode: InferenceMode
    fixture_dir: Path | None
    owner_id: str
    model_dir: Path = Path("models/mvsep_mega")
    mvsep_script: Path = Path("infer_mvsep_mega.py")
    skip_model_checksum: bool = False
    device: str = "auto"
    mvsep_python: Path | None = None
    job_execution: JobExecution = JobExecution.INLINE
    worker_id: str = "local-worker"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if environ is None else environ
        database_url = values.get(
            "DATABASE_URL", "sqlite+pysqlite:///./fretflow-local.db"
        ).strip()
        artifact_root = Path(
            values.get("FRETFLOW_ARTIFACT_ROOT", "./var/artifacts")
        ).expanduser()
        fixture_value = values.get("FRETFLOW_FIXTURE_DIR", "").strip()
        owner_id = values.get("FRETFLOW_LOCAL_OWNER_ID", "local-user").strip()
        model_dir = Path(
            values.get("FRETFLOW_MODEL_DIR", "models/mvsep_mega")
        ).expanduser()
        mvsep_script = Path(
            values.get("FRETFLOW_MVSEP_SCRIPT", "infer_mvsep_mega.py")
        ).expanduser()
        skip_model_checksum = values.get(
            "FRETFLOW_SKIP_MODEL_CHECKSUM", "false"
        ).lower() in {"1", "true", "yes"}

        device = values.get("FRETFLOW_DEVICE", "auto").strip().lower() or "auto"
        if device.split(":", 1)[0] not in DEVICE_CHOICES:
            raise ConfigurationError(
                "FRETFLOW_DEVICE must be auto, cuda, cuda:N, mps, or cpu"
            )
        mvsep_python_value = values.get("FRETFLOW_MVSEP_PYTHON", "").strip()
        worker_id = (
            values.get("FRETFLOW_WORKER_ID", "").strip() or socket.gethostname()
        )
        try:
            job_execution = JobExecution(
                values.get("FRETFLOW_JOB_EXECUTION", JobExecution.INLINE.value)
                .strip()
                .lower()
            )
        except ValueError as error:
            raise ConfigurationError(
                "FRETFLOW_JOB_EXECUTION must be inline or queue"
            ) from error

        try:
            inference_mode = InferenceMode(
                values.get("INFERENCE_MODE", InferenceMode.FIXTURE.value).lower()
            )
        except ValueError as error:
            raise ConfigurationError("INFERENCE_MODE must be fixture or real") from error

        if not database_url:
            raise ConfigurationError("DATABASE_URL must not be blank")
        if not owner_id:
            raise ConfigurationError("FRETFLOW_LOCAL_OWNER_ID must not be blank")

        return cls(
            database_url=database_url,
            artifact_root=artifact_root,
            inference_mode=inference_mode,
            fixture_dir=Path(fixture_value).expanduser() if fixture_value else None,
            owner_id=owner_id,
            model_dir=model_dir,
            mvsep_script=mvsep_script,
            skip_model_checksum=skip_model_checksum,
            device=device,
            mvsep_python=(
                Path(mvsep_python_value).expanduser() if mvsep_python_value else None
            ),
            job_execution=job_execution,
            worker_id=worker_id,
        )

    @property
    def mvsep_interpreter(self) -> Path:
        """Python used for MVSep; may differ from the worker's own interpreter."""

        return self.mvsep_python or Path(sys.executable)
