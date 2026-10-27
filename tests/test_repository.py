from dataclasses import replace
from pathlib import Path

import pytest

from fretflow.database import Base, create_database_engine, create_session_factory
from fretflow.domain import (
    ArtifactStatus,
    JobStatus,
    SeparationJob,
    Song,
    SongStatus,
    Stem,
    StemType,
    Tab,
    TabOptions,
    utc_now,
)
from fretflow.repository import (
    RecordNotFoundError,
    RepositoryConflictError,
    SqlAlchemyJobRepository,
    tab_options_fingerprint,
)

SONG_ID = "11111111-1111-4111-8111-111111111111"
SEPARATION_ID = "22222222-2222-4222-8222-222222222222"
STEM_ID = "33333333-3333-4333-8333-333333333333"
TAB_ID = "44444444-4444-4444-8444-444444444444"
TAB_JOB_ID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def repository(tmp_path: Path) -> SqlAlchemyJobRepository:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'repo.sqlite'}")
    Base.metadata.create_all(engine)
    return SqlAlchemyJobRepository(create_session_factory(engine))


def song(owner: str = "local-user") -> Song:
    return Song(
        song_id=SONG_ID,
        owner_id=owner,
        title="Fixture Song",
        source_filename="fixture.mp3",
        source_artifact_key=f"songs/{SONG_ID}/source/source.mp3",
        media_type="audio/mpeg",
    )


def separation(owner: str = "local-user") -> SeparationJob:
    return SeparationJob(
        job_id=SEPARATION_ID,
        song_id=SONG_ID,
        owner_id=owner,
        requested_stems=(StemType.ACOUSTIC_GUITAR, StemType.DRUMS),
        auto_tab_stems=(StemType.ACOUSTIC_GUITAR,),
    )


def stem(stem_id: str = STEM_ID, owner: str = "local-user") -> Stem:
    return Stem(
        stem_id=stem_id,
        song_id=SONG_ID,
        separation_job_id=SEPARATION_ID,
        owner_id=owner,
        stem_type=StemType.ACOUSTIC_GUITAR,
        artifact_key=(
            f"songs/{SONG_ID}/separations/{SEPARATION_ID}/stems/acoustic-guitar.wav"
        ),
        status=ArtifactStatus.READY,
    )


def tab(tab_id: str = TAB_ID, owner: str = "local-user") -> Tab:
    return Tab(
        tab_id=tab_id,
        job_id=TAB_JOB_ID,
        song_id=SONG_ID,
        stem_id=STEM_ID,
        owner_id=owner,
        options=TabOptions(tuning="drop-d"),
    )


def seed_to_stem(repository: SqlAlchemyJobRepository) -> None:
    repository.create_song(song())
    repository.create_separation_job(separation())
    repository.create_stem(stem())


def test_song_repository_is_owner_scoped_and_searchable(repository):
    repository.create_song(song())
    assert repository.get_song("local-user", SONG_ID).title == "Fixture Song"
    assert repository.list_songs("local-user", search="fixture")
    assert repository.list_songs("local-user", status=SongStatus.UPLOADING)
    assert repository.list_songs("local-user", search="missing") == []
    with pytest.raises(RecordNotFoundError):
        repository.get_song("another-user", SONG_ID)


def test_duplicate_song_is_reported_as_a_repository_conflict(repository):
    repository.create_song(song())
    with pytest.raises(RepositoryConflictError):
        repository.create_song(song())


def test_job_and_stem_round_trip_and_stem_creation_is_idempotent(repository):
    seed_to_stem(repository)
    stored_job = repository.get_separation_job("local-user", SEPARATION_ID)
    assert stored_job.auto_tab_stems == (StemType.ACOUSTIC_GUITAR,)
    assert repository.list_stems("local-user", SONG_ID)[0].status is ArtifactStatus.READY

    duplicate_request = stem(
        stem_id="66666666-6666-4666-8666-666666666666"
    )
    assert repository.create_stem(duplicate_request).stem_id == STEM_ID


def test_repository_updates_song_job_and_tab_state(repository):
    seed_to_stem(repository)
    ready_song = replace(song(), status=SongStatus.READY, updated_at=utc_now())
    repository.update_song(ready_song)
    assert repository.get_song("local-user", SONG_ID).status is SongStatus.READY

    running_job = replace(
        separation(), status=JobStatus.RUNNING, stage="separating", progress_percent=40
    )
    repository.update_separation_job(running_job)
    assert repository.get_separation_job("local-user", SEPARATION_ID).progress_percent == 40

    repository.create_tab(tab())
    completed = replace(
        tab(),
        status=JobStatus.SUCCEEDED,
        stage="complete",
        progress_percent=100,
        midi_artifact_key=f"songs/{SONG_ID}/tabs/{TAB_ID}/transcription.mid",
        tab_artifact_key=f"songs/{SONG_ID}/tabs/{TAB_ID}/transcription.tab.json",
        event_count=10,
    )
    repository.update_tab(completed)
    assert repository.get_tab("local-user", TAB_ID).event_count == 10
    assert repository.list_tabs("local-user", status=JobStatus.SUCCEEDED)[0].tab_id == TAB_ID


def test_tab_creation_reuses_the_existing_stem_and_options_request(repository):
    seed_to_stem(repository)
    repository.create_tab(tab())
    duplicate = Tab(
        tab_id="77777777-7777-4777-8777-777777777777",
        job_id="88888888-8888-4888-8888-888888888888",
        song_id=SONG_ID,
        stem_id=STEM_ID,
        owner_id="local-user",
        options=TabOptions(tuning="drop-d"),
    )
    assert repository.create_tab(duplicate).tab_id == TAB_ID
    assert len(repository.list_tabs("local-user")) == 1


def test_deleting_song_cascades_jobs_stems_and_tabs(repository):
    seed_to_stem(repository)
    repository.create_tab(tab())
    repository.delete_song("local-user", SONG_ID)
    with pytest.raises(RecordNotFoundError):
        repository.get_song("local-user", SONG_ID)
    with pytest.raises(RecordNotFoundError):
        repository.get_separation_job("local-user", SEPARATION_ID)
    with pytest.raises(RecordNotFoundError):
        repository.get_tab("local-user", TAB_ID)


def test_tab_options_fingerprint_is_stable_and_parameter_sensitive():
    first = tab_options_fingerprint(TabOptions(tuning="standard"))
    assert first == tab_options_fingerprint(TabOptions(tuning="standard"))
    assert first != tab_options_fingerprint(TabOptions(tuning="drop-d"))
