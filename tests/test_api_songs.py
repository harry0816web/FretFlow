import hashlib


def test_song_upload_library_file_and_delete_flow(api_context):
    create = api_context.client.post(
        "/api/songs",
        json={"title": "My Song", "source_filename": "track.mp3"},
    )
    assert create.status_code == 201
    song = create.json()
    assert song["status"] == "UPLOADING"
    assert song["source_artifact_key"].endswith("/source/source.mp3")

    upload = api_context.client.post(
        f"/api/songs/{song['song_id']}/upload",
        files={"file": ("track.mp3", b"audio-bytes", "audio/mpeg")},
    )
    assert upload.status_code == 200
    assert upload.json()["size_bytes"] == len(b"audio-bytes")

    complete = api_context.client.post(
        f"/api/songs/{song['song_id']}/upload-complete"
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "READY"
    assert complete.json()["sha256"] == hashlib.sha256(b"audio-bytes").hexdigest()

    listing = api_context.client.get("/api/songs", params={"search": "my"})
    assert [item["song_id"] for item in listing.json()] == [song["song_id"]]
    fetched = api_context.client.get(f"/api/songs/{song['song_id']}")
    assert fetched.json()["title"] == "My Song"
    artifact = api_context.client.get(
        f"/api/files/{song['source_artifact_key']}"
    )
    assert artifact.content == b"audio-bytes"

    confirmation = api_context.client.delete(f"/api/songs/{song['song_id']}")
    assert confirmation.status_code == 400
    assert confirmation.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    deleted = api_context.client.delete(
        f"/api/songs/{song['song_id']}", params={"confirm": "true"}
    )
    assert deleted.status_code == 204
    assert api_context.client.get(f"/api/songs/{song['song_id']}").status_code == 404


def test_song_upload_rejects_empty_or_duplicate_artifacts(api_context):
    song = api_context.client.post(
        "/api/songs",
        json={"title": "Empty", "source_filename": "empty.wav"},
    ).json()
    empty = api_context.client.post(
        f"/api/songs/{song['song_id']}/upload",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "EMPTY_UPLOAD"

    first = api_context.client.post(
        f"/api/songs/{song['song_id']}/upload",
        files={"file": ("empty.wav", b"one", "audio/wav")},
    )
    assert first.status_code == 200
    duplicate = api_context.client.post(
        f"/api/songs/{song['song_id']}/upload",
        files={"file": ("empty.wav", b"two", "audio/wav")},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ARTIFACT_EXISTS"


def test_song_handlers_return_stable_validation_and_not_found_errors(api_context):
    invalid = api_context.client.post(
        "/api/songs", json={"title": "", "source_filename": "track.mp3"}
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_REQUEST"

    missing = api_context.client.get(
        "/api/songs/99999999-9999-4999-8999-999999999999"
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RECORD_NOT_FOUND"
