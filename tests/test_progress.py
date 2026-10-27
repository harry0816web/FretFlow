import pytest

from fretflow.domain import DomainValidationError
from fretflow.progress import ProgressEvent, report_progress


def test_report_progress_returns_and_delivers_the_same_event():
    received = []
    event = report_progress(received.append, "separating", 50, "halfway")
    assert received == [event]
    assert event == ProgressEvent("separating", 50, "halfway")


def test_report_progress_allows_no_callback():
    assert report_progress(None, "queued", 0).progress_percent == 0


@pytest.mark.parametrize(
    ("stage", "percent"), [("", 1), ("running", -1), ("running", 101)]
)
def test_progress_event_rejects_invalid_stage_or_percent(stage, percent):
    with pytest.raises(DomainValidationError):
        ProgressEvent(stage, percent)
