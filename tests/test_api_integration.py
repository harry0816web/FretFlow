import json
from pathlib import Path

from fastapi.testclient import TestClient

from fretflow.api import ApiServices, create_app
from fretflow.artifacts import LocalArtifactStore
from fretflow.database import Base, create_database_engine, create_session_factory
from fretflow.pipeline import Pipeline
from fretflow.repository import SqlAlchemyJobRepository
from fretflow.services.fixture import FixtureStemSeparator, FixtureTabTranscriber


def test_http_fixture_flow_from_upload_through_auto_tab(tmp_path: Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'e2e.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyJobRepository(create_session_factory(engine))
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    midi = tmp_path / "demo.mid"
    midi.write_bytes(b"MThd")
    tab_json = tmp_path / "demo.tab.json"
    tab_json.write_text(
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
        transcriber=FixtureTabTranscriber(
            midi_fixture=midi,
            tab_fixture=tab_json,
        ),
        work_root=tmp_path / "work",
    )
    client = TestClient(
        create_app(
            ApiServices(
                repository=repository,
                artifacts=artifacts,
                owner_id="local-user",
                pipeline=pipeline,
                execute_jobs=True,
            )
        )
    )

    song = client.post(
        "/api/songs",
        json={
            "title": "2-in-1 fixture",
            "source_filename": "fixture.wav",
            "media_type": "audio/wav",
        },
    ).json()
    assert client.post(
        f"/api/songs/{song['song_id']}/upload",
        files={"file": ("fixture.wav", b"fixture-audio", "audio/wav")},
    ).status_code == 200
    assert client.post(
        f"/api/songs/{song['song_id']}/upload-complete"
    ).status_code == 200

    separation = client.post(
        f"/api/songs/{song['song_id']}/separations",
        json={
            "requested_stems": ["acoustic-guitar", "drums"],
            "auto_tab": True,
        },
    )
    assert separation.status_code == 201
    job_id = separation.json()["job_id"]
    assert client.get(f"/api/separations/{job_id}").json()["status"] == "SUCCEEDED"

    stems = client.get(f"/api/songs/{song['song_id']}/stems").json()
    assert [stem["stem_type"] for stem in stems] == ["acoustic-guitar", "drums"]
    tabs = client.get("/api/tabs").json()
    assert len(tabs) == 1
    assert tabs[0]["status"] == "SUCCEEDED"
    assert tabs[0]["event_count"] == 1
    assert client.get(tabs[0]["tab_url"]).json()["events"][0]["onset_seconds"] == 0.1
    assert client.get(stems[0]["artifact_url"]).content == b"fixture-audio"
