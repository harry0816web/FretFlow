from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from fretflow.manifest import ArtifactManifest, ManifestArtifact, ManifestKind

SONG_ID = "11111111-1111-4111-8111-111111111111"
JOB_ID = "22222222-2222-4222-8222-222222222222"


def artifact(name: str = "acoustic-guitar.wav") -> ManifestArtifact:
    return ManifestArtifact(
        key=f"songs/{SONG_ID}/separations/{JOB_ID}/stems/{name}",
        sha256="a" * 64,
        size_bytes=123,
        media_type="audio/wav",
    )


def test_manifest_serializes_a_versioned_owner_scoped_record():
    manifest = ArtifactManifest(
        kind=ManifestKind.SEPARATION,
        owner_id="local-user",
        song_id=SONG_ID,
        job_id=JOB_ID,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        artifacts=[artifact()],
        diagnostics={"rtf": 0.8},
    )
    payload = manifest.model_dump(mode="json")
    assert payload["schema_version"] == "1.0"
    assert payload["kind"] == "separation"
    assert payload["artifacts"][0]["size_bytes"] == 123


@pytest.mark.parametrize(
    "changes",
    [
        {"owner_id": " "},
        {"created_at": datetime(2026, 1, 1)},
        {"artifacts": []},
        {"artifacts": [artifact(), artifact()]},
        {
            "artifacts": [
                ManifestArtifact(
                    key=(
                        "songs/99999999-9999-4999-8999-999999999999/"
                        "tabs/result.json"
                    ),
                    sha256="b" * 64,
                    size_bytes=1,
                )
            ]
        },
    ],
)
def test_manifest_rejects_invalid_identity_time_or_artifacts(changes):
    values = {
        "kind": ManifestKind.SEPARATION,
        "owner_id": "local-user",
        "song_id": SONG_ID,
        "job_id": JOB_ID,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "artifacts": [artifact()],
    }
    values.update(changes)
    with pytest.raises(ValidationError):
        ArtifactManifest(**values)


@pytest.mark.parametrize(
    "changes",
    [
        {"key": "/absolute.wav"},
        {"sha256": "not-a-digest"},
        {"size_bytes": -1},
    ],
)
def test_manifest_artifact_rejects_unsafe_or_invalid_metadata(changes):
    values = {
        "key": f"songs/{SONG_ID}/tabs/{JOB_ID}/transcription.mid",
        "sha256": "a" * 64,
        "size_bytes": 10,
    }
    values.update(changes)
    with pytest.raises((ValidationError, ValueError)):
        ManifestArtifact(**values)
