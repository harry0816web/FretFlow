import json
from pathlib import Path

import pytest

from fretflow.artifacts import LocalArtifactStore
from fretflow.database import Base, create_database_engine, create_session_factory
from fretflow.domain import (
    JobStatus,
    SeparationJob,
    Song,
    SongStatus,
    StemType,
)
from fretflow.pipeline import Pipeline
from fretflow.repository import SqlAlchemyJobRepository
from fretflow.services.fixture import FixtureStemSeparator, FixtureTabTranscriber

SONG_ID = "11111111-1111-4111-8111-111111111111"
JOB_ID = "22222222-2222-4222-8222-222222222222"


def build_pipeline(tmp_path: Path, *, transcriber=None):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'pipeline.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyJobRepository(create_session_factory(engine))
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    source_key = f"songs/{SONG_ID}/source/source.wav"
    artifacts.put_file(source, source_key)
    repository.create_song(
        Song(
            song_id=SONG_ID,
            owner_id="local-user",
            title="Pipeline fixture",
            source_filename="source.wav",
            source_artifact_key=source_key,
            media_type="audio/wav",
        )
    )
    repository.create_separation_job(
        SeparationJob(
            job_id=JOB_ID,
            song_id=SONG_ID,
            owner_id="local-user",
            requested_stems=(StemType.ACOUSTIC_GUITAR, StemType.DRUMS),
            auto_tab_stems=(StemType.ACOUSTIC_GUITAR,),
        )
    )
    midi = tmp_path / "fixture.mid"
    midi.write_bytes(b"MThd")
    tab = tmp_path / "fixture.tab.json"
    tab.write_text(
        json.dumps(
            {
                "events": [{"onset_seconds": 0.1, "notes": []}],
                "diagnostics": {"dropped_note_assignments": 0},
            }
        ),
        encoding="utf-8",
    )
    pipeline = Pipeline(
        repository=repository,
        artifacts=artifacts,
        separator=FixtureStemSeparator(),
        transcriber=transcriber
        or FixtureTabTranscriber(midi_fixture=midi, tab_fixture=tab),
        work_root=tmp_path / "work",
    )
    return pipeline, repository, artifacts


def test_pipeline_runs_two_in_one_flow_and_is_idempotent(tmp_path: Path):
    pipeline, repository, artifacts = build_pipeline(tmp_path)

    stems = pipeline.run_separation("local-user", JOB_ID)

    assert len(stems) == 2
    assert repository.get_separation_job("local-user", JOB_ID).status is JobStatus.SUCCEEDED
    assert repository.get_song("local-user", SONG_ID).status is SongStatus.READY
    tabs = repository.list_tabs("local-user")
    assert len(tabs) == 1
    assert tabs[0].status is JobStatus.SUCCEEDED
    assert tabs[0].tab_artifact_key is not None
    assert artifacts.exists(tabs[0].tab_artifact_key)

    rerun = pipeline.run_separation("local-user", JOB_ID)
    assert [stem.stem_id for stem in rerun] == [stem.stem_id for stem in stems]
    assert len(repository.list_tabs("local-user")) == 1


def test_tab_failure_preserves_stems_and_marks_song_partial(tmp_path: Path):
    class FailingTranscriber:
        def transcribe(self, *_args, **_kwargs):
            raise RuntimeError("fixture transcription failed")

    pipeline, repository, _ = build_pipeline(
        tmp_path, transcriber=FailingTranscriber()
    )

    stems = pipeline.run_separation("local-user", JOB_ID)

    assert len(stems) == 2
    assert repository.get_song("local-user", SONG_ID).status is SongStatus.PARTIAL_FAILED
    assert repository.get_separation_job("local-user", JOB_ID).status is JobStatus.SUCCEEDED
    assert repository.list_tabs("local-user")[0].status is JobStatus.FAILED


def test_separation_failure_marks_job_and_song_failed(tmp_path: Path):
    pipeline, repository, _ = build_pipeline(tmp_path)

    class FailingSeparator:
        def separate(self, *_args, **_kwargs):
            raise RuntimeError("fixture separation failed")

    pipeline._separator = FailingSeparator()
    with pytest.raises(RuntimeError, match="fixture separation failed"):
        pipeline.run_separation("local-user", JOB_ID)

    assert repository.get_separation_job("local-user", JOB_ID).status is JobStatus.FAILED
    assert repository.get_song("local-user", SONG_ID).status is SongStatus.FAILED
