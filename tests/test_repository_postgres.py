import os
from uuid import uuid4

import pytest

from fretflow.database import create_database_engine, create_session_factory
from fretflow.domain import SeparationJob, Song, Stem, StemType, Tab, TabOptions
from fretflow.repository import SqlAlchemyJobRepository


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL integration URL is unavailable",
)
def test_postgres_repository_round_trip_and_cleanup():
    owner_id = f"postgres-test-{uuid4()}"
    song_id = str(uuid4())
    separation_id = str(uuid4())
    stem_id = str(uuid4())
    tab_id = str(uuid4())
    repository = SqlAlchemyJobRepository(
        create_session_factory(create_database_engine(os.environ["DATABASE_URL"]))
    )
    song = Song(
        song_id=song_id,
        owner_id=owner_id,
        title="PostgreSQL smoke",
        source_filename="source.wav",
        source_artifact_key=f"songs/{song_id}/source/source.wav",
        media_type="audio/wav",
    )
    job = SeparationJob(
        job_id=separation_id,
        song_id=song_id,
        owner_id=owner_id,
        requested_stems=(StemType.ACOUSTIC_GUITAR,),
    )
    stem = Stem(
        stem_id=stem_id,
        song_id=song_id,
        separation_job_id=separation_id,
        owner_id=owner_id,
        stem_type=StemType.ACOUSTIC_GUITAR,
        artifact_key=(
            f"songs/{song_id}/separations/{separation_id}/stems/acoustic-guitar.wav"
        ),
    )
    tab = Tab(
        tab_id=tab_id,
        job_id=str(uuid4()),
        song_id=song_id,
        stem_id=stem_id,
        owner_id=owner_id,
        options=TabOptions(),
    )

    try:
        repository.create_song(song)
        repository.create_separation_job(job)
        repository.create_stem(stem)
        repository.create_tab(tab)
        assert repository.get_song(owner_id, song_id).title == "PostgreSQL smoke"
        assert repository.get_tab(owner_id, tab_id).stem_id == stem_id
    finally:
        try:
            repository.delete_song(owner_id, song_id)
        except Exception:
            pass
