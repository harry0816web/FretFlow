"""Progress events shared by inference services and job orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fretflow.domain import DomainValidationError


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    stage: str
    progress_percent: int
    message: str | None = None

    def __post_init__(self) -> None:
        if not self.stage.strip():
            raise DomainValidationError("progress stage must not be blank")
        if not 0 <= self.progress_percent <= 100:
            raise DomainValidationError("progress percent must be between 0 and 100")


ProgressCallback = Callable[[ProgressEvent], None]


def report_progress(
    callback: ProgressCallback | None,
    stage: str,
    progress_percent: int,
    message: str | None = None,
) -> ProgressEvent:
    """Create a validated event and deliver it when a callback is registered."""

    event = ProgressEvent(stage, progress_percent, message)
    if callback is not None:
        callback(event)
    return event
