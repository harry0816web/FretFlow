from datetime import datetime, timezone

import pytest

from fretflow.domain import (
    ArtifactStatus,
    DEFAULT_STEMS,
    DomainValidationError,
    SeparationJob,
    Song,
    Stem,
    StemType,
    Tab,
    TabOptions,
    JobStatus,
    normalize_stems,
    select_auto_tab_stems,
    utc_now,
    validate_artifact_key,
    validate_job_transition,
)

SONG_ID = "11111111-1111-4111-8111-111111111111"
SEPARATION_ID = "22222222-2222-4222-8222-222222222222"
STEM_ID = "33333333-3333-4333-8333-333333333333"
TAB_ID = "44444444-4444-4444-8444-444444444444"
TAB_JOB_ID = "55555555-5555-4555-8555-555555555555"


def test_normalize_stems_preserves_order_and_removes_duplicates():
    assert normalize_stems(["drums", "acoustic-guitar", "drums"]) == (
        StemType.DRUMS,
        StemType.ACOUSTIC_GUITAR,
    )


@pytest.mark.parametrize("values", [[], ["piano"]])
def test_normalize_stems_rejects_empty_or_unsupported_values(values):
    with pytest.raises(DomainValidationError):
        normalize_stems(values)


def test_only_guitar_stems_are_tab_eligible():
    assert select_auto_tab_stems(StemType, enabled=True) == DEFAULT_STEMS
    assert select_auto_tab_stems(DEFAULT_STEMS, enabled=False) == ()


def test_tab_options_accept_valid_custom_values():
    options = TabOptions(tuning="drop-d", capo=2, max_fret=24, max_stretch=6)
    assert options.tuning == "drop-d"
    assert options.capo == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capo", 13),
        ("max_fret", 11),
        ("max_stretch", 0),
        ("onset_tolerance", 0),
        ("candidate_limit", 0),
        ("onset_threshold", 1),
        ("minimum_note_length_ms", 0),
    ],
)
def test_tab_options_reject_invalid_ranges(field, value):
    with pytest.raises(DomainValidationError):
        TabOptions(**{field: value})


def test_utc_now_returns_an_aware_timestamp():
    assert utc_now().utcoffset() == timezone.utc.utcoffset(None)


@pytest.mark.parametrize(
    "key", ["/absolute.wav", "songs/a/../b.wav", "songs//a.wav", "songs\\a.wav"]
)
def test_validate_artifact_key_rejects_unsafe_paths(key):
    with pytest.raises(DomainValidationError):
        validate_artifact_key(key)


def test_validate_job_transition_supports_execution_retry_and_idempotency():
    assert validate_job_transition("QUEUED", "RUNNING") is JobStatus.RUNNING
    assert validate_job_transition(JobStatus.FAILED, JobStatus.QUEUED) is JobStatus.QUEUED
    assert validate_job_transition(JobStatus.RUNNING, JobStatus.RUNNING) is JobStatus.RUNNING


@pytest.mark.parametrize(
    ("current", "target"),
    [(JobStatus.SUCCEEDED, JobStatus.RUNNING), (JobStatus.QUEUED, JobStatus.SUCCEEDED)],
)
def test_validate_job_transition_rejects_skipped_or_terminal_transitions(
    current, target
):
    with pytest.raises(DomainValidationError):
        validate_job_transition(current, target)


def test_song_accepts_owner_scoped_source_metadata():
    song = Song(
        song_id=SONG_ID,
        owner_id="local-user",
        title="Fixture song",
        source_filename="fixture.mp3",
        source_artifact_key=f"songs/{SONG_ID}/source/source.mp3",
        media_type="audio/mpeg",
        duration_seconds=30.0,
        sha256="a" * 64,
    )
    assert song.status.value == "UPLOADING"
    assert song.duration_seconds == 30.0


@pytest.mark.parametrize(
    "changes",
    [
        {"song_id": "not-a-uuid"},
        {"source_artifact_key": f"songs/{SEPARATION_ID}/source/source.mp3"},
        {"duration_seconds": -1},
        {"sha256": "ABC"},
        {"created_at": datetime(2026, 1, 1)},
    ],
)
def test_song_rejects_invalid_identity_artifact_or_metadata(changes):
    values = {
        "song_id": SONG_ID,
        "owner_id": "local-user",
        "title": "Fixture song",
        "source_filename": "fixture.mp3",
        "source_artifact_key": f"songs/{SONG_ID}/source/source.mp3",
        "media_type": "audio/mpeg",
    }
    values.update(changes)
    with pytest.raises(DomainValidationError):
        Song(**values)


def test_separation_job_normalizes_requested_and_auto_tab_stems():
    job = SeparationJob(
        job_id=SEPARATION_ID,
        song_id=SONG_ID,
        owner_id="local-user",
        requested_stems=(StemType.DRUMS, StemType.ACOUSTIC_GUITAR, StemType.DRUMS),
        auto_tab_stems=(StemType.ACOUSTIC_GUITAR,),
    )
    assert job.requested_stems == (StemType.DRUMS, StemType.ACOUSTIC_GUITAR)
    assert job.auto_tab_stems == (StemType.ACOUSTIC_GUITAR,)


@pytest.mark.parametrize(
    "auto_stems,progress",
    [((StemType.BASS,), 0), ((StemType.ELECTRIC_GUITAR,), 0), ((), 101)],
)
def test_separation_job_rejects_ineligible_missing_or_invalid_progress(
    auto_stems, progress
):
    with pytest.raises(DomainValidationError):
        SeparationJob(
            job_id=SEPARATION_ID,
            song_id=SONG_ID,
            owner_id="local-user",
            requested_stems=(StemType.ACOUSTIC_GUITAR, StemType.BASS),
            auto_tab_stems=auto_stems,
            progress_percent=progress,
        )


def test_stem_derives_tab_eligibility_from_the_allowlist():
    stem = Stem(
        stem_id=STEM_ID,
        song_id=SONG_ID,
        separation_job_id=SEPARATION_ID,
        owner_id="local-user",
        stem_type=StemType.ELECTRIC_GUITAR,
        artifact_key=(
            f"songs/{SONG_ID}/separations/{SEPARATION_ID}/stems/electric-guitar.wav"
        ),
        status=ArtifactStatus.READY,
        sample_rate=44_100,
        channels=2,
    )
    assert stem.tab_eligible


def test_stem_rejects_artifact_from_another_separation():
    with pytest.raises(DomainValidationError):
        Stem(
            stem_id=STEM_ID,
            song_id=SONG_ID,
            separation_job_id=SEPARATION_ID,
            owner_id="local-user",
            stem_type=StemType.DRUMS,
            artifact_key=f"songs/{SONG_ID}/separations/other/stems/drums.wav",
        )


def test_tab_accepts_artifacts_scoped_to_its_identity():
    tab = Tab(
        tab_id=TAB_ID,
        job_id=TAB_JOB_ID,
        song_id=SONG_ID,
        stem_id=STEM_ID,
        owner_id="local-user",
        options=TabOptions(tuning="drop-d"),
        midi_artifact_key=f"songs/{SONG_ID}/tabs/{TAB_ID}/transcription.mid",
        tab_artifact_key=f"songs/{SONG_ID}/tabs/{TAB_ID}/transcription.tab.json",
        event_count=12,
    )
    assert tab.options.tuning == "drop-d"
    assert tab.event_count == 12


@pytest.mark.parametrize(
    "changes",
    [
        {"progress_percent": -1},
        {"event_count": -1},
        {"midi_artifact_key": f"songs/{SONG_ID}/tabs/other/file.mid"},
        {"options": "standard"},
    ],
)
def test_tab_rejects_invalid_progress_counts_or_artifact_scope(changes):
    values = {
        "tab_id": TAB_ID,
        "job_id": TAB_JOB_ID,
        "song_id": SONG_ID,
        "stem_id": STEM_ID,
        "owner_id": "local-user",
        "options": TabOptions(),
    }
    values.update(changes)
    with pytest.raises(DomainValidationError):
        Tab(**values)
