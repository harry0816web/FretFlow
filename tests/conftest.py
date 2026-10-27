from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fretflow.api import ApiServices, create_app
from fretflow.artifacts import LocalArtifactStore
from fretflow.database import Base, create_database_engine, create_session_factory
from fretflow.repository import SqlAlchemyJobRepository


@dataclass
class ApiContext:
    client: TestClient
    repository: SqlAlchemyJobRepository
    artifacts: LocalArtifactStore


@pytest.fixture
def api_context(tmp_path: Path) -> ApiContext:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'api.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyJobRepository(create_session_factory(engine))
    artifacts = LocalArtifactStore(tmp_path / "artifacts")
    app = create_app(
        ApiServices(
            repository=repository,
            artifacts=artifacts,
            owner_id="local-user",
        )
    )
    return ApiContext(TestClient(app), repository, artifacts)


@pytest.fixture
def uploaded_song(api_context: ApiContext) -> dict:
    response = api_context.client.post(
        "/api/songs",
        json={
            "title": "API Fixture",
            "source_filename": "fixture.wav",
            "media_type": "audio/wav",
        },
    )
    song = response.json()
    upload = api_context.client.post(
        f"/api/songs/{song['song_id']}/upload",
        files={"file": ("fixture.wav", b"fixture-audio", "audio/wav")},
    )
    assert upload.status_code == 200
    completed = api_context.client.post(
        f"/api/songs/{song['song_id']}/upload-complete"
    )
    assert completed.status_code == 200
    return completed.json()
