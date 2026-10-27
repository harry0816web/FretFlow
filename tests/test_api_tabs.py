from dataclasses import replace
from uuid import uuid4

from fretflow.domain import ArtifactStatus, JobStatus, SeparationJob, Stem, StemType


def seed_stem(api_context, uploaded_song, stem_type=StemType.ACOUSTIC_GUITAR):
    job_id = str(uuid4())
    stem_id = str(uuid4())
    api_context.repository.create_separation_job(
        SeparationJob(
            job_id=job_id,
            song_id=uploaded_song["song_id"],
            owner_id="local-user",
            requested_stems=(stem_type,),
        )
    )
    source = api_context.artifacts.materialize(uploaded_song["source_artifact_key"])
    key = (
        f"songs/{uploaded_song['song_id']}/separations/{job_id}/stems/"
        f"{stem_type.value}.wav"
    )
    api_context.artifacts.put_file(source, key)
    return api_context.repository.create_stem(
        Stem(
            stem_id=stem_id,
            song_id=uploaded_song["song_id"],
            separation_job_id=job_id,
            owner_id="local-user",
            stem_type=stem_type,
            artifact_key=key,
            status=ArtifactStatus.READY,
        )
    )


def test_create_list_get_and_deduplicate_tab(api_context, uploaded_song):
    stem = seed_stem(api_context, uploaded_song)
    payload = {"tuning": "drop-d", "capo": 2}
    created = api_context.client.post(
        f"/api/stems/{stem.stem_id}/tabs", json=payload
    )
    assert created.status_code == 201
    tab = created.json()
    assert tab["tuning"] == "drop-d"
    assert tab["capo"] == 2

    duplicate = api_context.client.post(
        f"/api/stems/{stem.stem_id}/tabs", json=payload
    )
    assert duplicate.json()["tab_id"] == tab["tab_id"]
    assert len(api_context.client.get("/api/tabs").json()) == 1
    assert api_context.client.get(f"/api/tabs/{tab['tab_id']}").json() == tab


def test_tab_rejects_non_guitar_stem_and_invalid_options(api_context, uploaded_song):
    drum = seed_stem(api_context, uploaded_song, StemType.DRUMS)
    unsupported = api_context.client.post(
        f"/api/stems/{drum.stem_id}/tabs", json={}
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "UNSUPPORTED_STEM"

    guitar = seed_stem(api_context, uploaded_song, StemType.ELECTRIC_GUITAR)
    invalid = api_context.client.post(
        f"/api/stems/{guitar.stem_id}/tabs", json={"capo": 99}
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "DOMAIN_VALIDATION_ERROR"


def test_failed_tab_can_be_retried(api_context, uploaded_song):
    stem = seed_stem(api_context, uploaded_song)
    created = api_context.client.post(f"/api/stems/{stem.stem_id}/tabs", json={}).json()
    tab = api_context.repository.get_tab("local-user", created["tab_id"])
    api_context.repository.update_tab(
        replace(
            tab,
            status=JobStatus.FAILED,
            stage="failed",
            error_code="TAB_FAILED",
            error_message="boom",
        )
    )

    retried = api_context.client.post(f"/api/tabs/{tab.tab_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "QUEUED"
    assert retried.json()["error_code"] is None
