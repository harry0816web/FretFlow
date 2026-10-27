import pytest

from validate_gpu_smoke import (
    PRODUCT_STEMS,
    ValidationError,
    validate_separation_manifest,
    validate_tab_payload,
)


def separation_manifest(stems=PRODUCT_STEMS):
    return {
        "schema_version": 1,
        "input": {"duration_seconds": 220.47},
        "model": {"selected_stems": list(stems)},
        "inference": {
            "elapsed_seconds": 6.6,
            "real_time_factor": 0.03,
            "model_load_seconds": 13.44,
            "peak_cuda_allocated_bytes": 1_524_712_857,
            "peak_cuda_reserved_bytes": 1_911_260_364,
        },
        "environment": {
            "gpu": "NVIDIA GeForce RTX 5090",
            "python": "3.11.14",
            "torch": "2.11.0+cu130",
            "torch_cuda": "13.0",
        },
        "outputs": [{"stem": stem} for stem in stems],
    }


def test_validate_separation_manifest_summarizes_gpu_metrics():
    summary = validate_separation_manifest(separation_manifest())

    assert summary["stems"] == list(PRODUCT_STEMS)
    assert summary["real_time_factor"] == 0.03
    assert summary["peak_cuda_allocated_gib"] == pytest.approx(1.42, abs=0.01)


def test_validate_separation_manifest_rejects_incomplete_stems():
    with pytest.raises(ValidationError, match="Expected stems"):
        validate_separation_manifest(
            separation_manifest(("acoustic-guitar", "electric-guitar"))
        )


def test_validate_tab_payload_requires_events_and_matching_source():
    payload = {
        "format": "basic-pitch-tab-v1",
        "input": {"path": "/outputs/acoustic-guitar.wav"},
        "transcription": {"elapsed_seconds": 3.2},
        "diagnostics": {"dropped_note_assignments": 2},
        "events": [{"onset_seconds": 0.1, "notes": [{"string": 1, "fret": 3}]}],
    }
    assert validate_tab_payload(payload, "acoustic-guitar")["event_count"] == 1

    payload["events"] = []
    with pytest.raises(ValidationError, match="no events"):
        validate_tab_payload(payload, "acoustic-guitar")
