from dataclasses import replace

from fretflow.domain import JobStatus


def test_create_and_poll_separation_with_auto_tab_filtering(api_context, uploaded_song):
    response = api_context.client.post(
        f"/api/songs/{uploaded_song['song_id']}/separations",
        json={
            "requested_stems": ["acoustic-guitar", "drums"],
            "auto_tab": True,
        },
    )
    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "QUEUED"
    assert job["auto_tab_stems"] == ["acoustic-guitar"]
    polled = api_context.client.get(f"/api/separations/{job['job_id']}")
    assert polled.json() == job


def test_separation_requires_completed_upload_and_product_allowlist(api_context):
    song = api_context.client.post(
        "/api/songs",
        json={"title": "Pending", "source_filename": "track.wav"},
    ).json()
    pending = api_context.client.post(
        f"/api/songs/{song['song_id']}/separations",
        json={"requested_stems": ["drums"]},
    )
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "UPLOAD_INCOMPLETE"

    unsupported = api_context.client.post(
        f"/api/songs/{song['song_id']}/separations",
        json={"requested_stems": ["piano"]},
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "INVALID_REQUEST"


def test_failed_separation_can_be_retried(api_context, uploaded_song):
    created = api_context.client.post(
        f"/api/songs/{uploaded_song['song_id']}/separations",
        json={"requested_stems": ["vocal"]},
    ).json()
    job = api_context.repository.get_separation_job("local-user", created["job_id"])
    api_context.repository.update_separation_job(
        replace(
            job,
            status=JobStatus.FAILED,
            stage="failed",
            error_code="MODEL_FAILED",
            error_message="boom",
        )
    )

    retried = api_context.client.post(f"/api/separations/{job.job_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "QUEUED"
    assert retried.json()["error_code"] is None

    conflict = api_context.client.post(f"/api/separations/{job.job_id}/retry")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "JOB_NOT_FAILED"
