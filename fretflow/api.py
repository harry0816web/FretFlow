"""FretFlow HTTP API."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from fretflow import __version__
from fretflow.api_schemas import (
    SeparationCreateRequest,
    SeparationResponse,
    SongCreateRequest,
    SongResponse,
    StemResponse,
    TabCreateRequest,
    TabResponse,
    UploadResponse,
)
from fretflow.artifacts import ArtifactStore, LocalArtifactStore
from fretflow.config import Settings
from fretflow.database import create_database_engine, create_session_factory
from fretflow.domain import (
    DEFAULT_STEMS,
    DomainValidationError,
    JobStatus,
    SeparationJob,
    Song,
    SongStatus,
    Stem,
    StemType,
    Tab,
    TabOptions,
    select_auto_tab_stems,
    utc_now,
    validate_artifact_key,
)
from fretflow.pipeline import Pipeline
from fretflow.repository import (
    JobRepository,
    RecordNotFoundError,
    RepositoryConflictError,
    SqlAlchemyJobRepository,
)
from fretflow.runtime import create_pipeline


class HealthResponse(BaseModel):
    status: str
    version: str


class StemTypeResponse(BaseModel):
    value: StemType
    tab_eligible: bool
    default_selected: bool


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any]


class ErrorResponse(BaseModel):
    error: ErrorDetail


@dataclass(slots=True)
class ApiServices:
    repository: JobRepository
    artifacts: ArtifactStore
    owner_id: str
    pipeline: Pipeline | None = None
    execute_jobs: bool = False


def error_response(
    *, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=details or {})
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def create_app(services: ApiServices | None = None) -> FastAPI:
    app = FastAPI(title="FretFlow API", version=__version__)
    app.state.services = services

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _: Request, exception: StarletteHTTPException
    ) -> JSONResponse:
        if isinstance(exception.detail, dict):
            return error_response(
                status_code=exception.status_code,
                code=str(exception.detail.get("code", f"HTTP_{exception.status_code}")),
                message=str(exception.detail.get("message", "Request failed")),
                details=dict(exception.detail.get("details", {})),
            )
        return error_response(
            status_code=exception.status_code,
            code=f"HTTP_{exception.status_code}",
            message=str(exception.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exception: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            status_code=422,
            code="INVALID_REQUEST",
            message="Request validation failed",
            details={"errors": jsonable_encoder(exception.errors())},
        )

    @app.exception_handler(DomainValidationError)
    async def handle_domain_error(
        _: Request, exception: DomainValidationError
    ) -> JSONResponse:
        return error_response(
            status_code=422,
            code="DOMAIN_VALIDATION_ERROR",
            message=str(exception),
        )

    @app.exception_handler(RecordNotFoundError)
    async def handle_not_found(
        _: Request, exception: RecordNotFoundError
    ) -> JSONResponse:
        return error_response(
            status_code=404, code="RECORD_NOT_FOUND", message=str(exception)
        )

    @app.exception_handler(RepositoryConflictError)
    async def handle_conflict(
        _: Request, exception: RepositoryConflictError
    ) -> JSONResponse:
        return error_response(status_code=409, code="CONFLICT", message=str(exception))

    @app.exception_handler(FileNotFoundError)
    async def handle_missing_artifact(
        _: Request, exception: FileNotFoundError
    ) -> JSONResponse:
        return error_response(
            status_code=404, code="ARTIFACT_NOT_FOUND", message=str(exception)
        )

    @app.exception_handler(FileExistsError)
    async def handle_existing_artifact(
        _: Request, exception: FileExistsError
    ) -> JSONResponse:
        return error_response(
            status_code=409, code="ARTIFACT_EXISTS", message=str(exception)
        )

    def get_services(request: Request) -> ApiServices:
        current = request.app.state.services
        if current is None:
            current = _create_default_services()
            request.app.state.services = current
        return current

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    @app.get("/api/stem-types", response_model=list[StemTypeResponse])
    def stem_types() -> list[StemTypeResponse]:
        return [
            StemTypeResponse(
                value=stem,
                tab_eligible=stem.tab_eligible,
                default_selected=stem in DEFAULT_STEMS,
            )
            for stem in StemType
        ]

    @app.post("/api/songs", response_model=SongResponse, status_code=201)
    def create_song(
        payload: SongCreateRequest,
        runtime: ApiServices = Depends(get_services),
    ) -> SongResponse:
        source_filename = Path(payload.source_filename).name
        suffix = Path(source_filename).suffix.lower() or ".bin"
        song_id = str(uuid4())
        song = Song(
            song_id=song_id,
            owner_id=runtime.owner_id,
            title=payload.title.strip(),
            source_filename=source_filename,
            source_artifact_key=f"songs/{song_id}/source/source{suffix}",
            media_type=payload.media_type,
        )
        return _song_response(runtime.repository.create_song(song))

    @app.post("/api/songs/{song_id}/upload", response_model=UploadResponse)
    async def upload_song(
        song_id: str,
        file: UploadFile = File(...),
        runtime: ApiServices = Depends(get_services),
    ) -> UploadResponse:
        song = runtime.repository.get_song(runtime.owner_id, song_id)
        with tempfile.NamedTemporaryFile(delete=False) as temporary:
            temporary_path = Path(temporary.name)
            size = 0
            while chunk := await file.read(1024 * 1024):
                temporary.write(chunk)
                size += len(chunk)
        try:
            if size == 0:
                _api_error(400, "EMPTY_UPLOAD", "Uploaded audio must not be empty")
            runtime.artifacts.put_file(temporary_path, song.source_artifact_key)
        finally:
            temporary_path.unlink(missing_ok=True)
            await file.close()
        return UploadResponse(
            song_id=song.song_id,
            artifact_key=song.source_artifact_key,
            size_bytes=size,
        )

    @app.post("/api/songs/{song_id}/upload-complete", response_model=SongResponse)
    def complete_upload(
        song_id: str, runtime: ApiServices = Depends(get_services)
    ) -> SongResponse:
        song = runtime.repository.get_song(runtime.owner_id, song_id)
        source = runtime.artifacts.materialize(song.source_artifact_key)
        if source.stat().st_size <= 0:
            _api_error(400, "EMPTY_UPLOAD", "Uploaded audio must not be empty")
        completed = replace(
            song,
            sha256=_sha256(source),
            status=SongStatus.READY,
            updated_at=utc_now(),
        )
        return _song_response(runtime.repository.update_song(completed))

    @app.get("/api/songs", response_model=list[SongResponse])
    def list_songs(
        search: str | None = None,
        status: SongStatus | None = None,
        runtime: ApiServices = Depends(get_services),
    ) -> list[SongResponse]:
        songs = runtime.repository.list_songs(
            runtime.owner_id, search=search, status=status
        )
        return [_song_response(song) for song in songs]

    @app.get("/api/songs/{song_id}", response_model=SongResponse)
    def get_song(
        song_id: str, runtime: ApiServices = Depends(get_services)
    ) -> SongResponse:
        return _song_response(runtime.repository.get_song(runtime.owner_id, song_id))

    @app.delete("/api/songs/{song_id}", status_code=204)
    def delete_song(
        song_id: str,
        confirm: bool = Query(False),
        runtime: ApiServices = Depends(get_services),
    ) -> None:
        if not confirm:
            _api_error(400, "CONFIRMATION_REQUIRED", "Song deletion requires confirmation")
        runtime.repository.get_song(runtime.owner_id, song_id)
        runtime.artifacts.delete_prefix(f"songs/{song_id}/")
        runtime.repository.delete_song(runtime.owner_id, song_id)

    @app.post(
        "/api/songs/{song_id}/separations",
        response_model=SeparationResponse,
        status_code=201,
    )
    def create_separation(
        song_id: str,
        payload: SeparationCreateRequest,
        background: BackgroundTasks,
        runtime: ApiServices = Depends(get_services),
    ) -> SeparationResponse:
        song = runtime.repository.get_song(runtime.owner_id, song_id)
        if song.status is SongStatus.UPLOADING:
            _api_error(409, "UPLOAD_INCOMPLETE", "Complete the upload before separation")
        auto_stems = select_auto_tab_stems(payload.requested_stems, payload.auto_tab)
        job = SeparationJob(
            job_id=str(uuid4()),
            song_id=song.song_id,
            owner_id=runtime.owner_id,
            requested_stems=tuple(payload.requested_stems),
            auto_tab_stems=auto_stems,
        )
        job = runtime.repository.create_separation_job(job)
        _schedule_separation(background, runtime, job.job_id)
        return _separation_response(job)

    @app.get("/api/separations/{job_id}", response_model=SeparationResponse)
    def get_separation(
        job_id: str, runtime: ApiServices = Depends(get_services)
    ) -> SeparationResponse:
        job = runtime.repository.get_separation_job(runtime.owner_id, job_id)
        return _separation_response(job)

    @app.post("/api/separations/{job_id}/retry", response_model=SeparationResponse)
    def retry_separation(
        job_id: str,
        background: BackgroundTasks,
        runtime: ApiServices = Depends(get_services),
    ) -> SeparationResponse:
        job = runtime.repository.get_separation_job(runtime.owner_id, job_id)
        if job.status is not JobStatus.FAILED:
            _api_error(409, "JOB_NOT_FAILED", "Only failed jobs can be retried")
        queued = replace(
            job,
            status=JobStatus.QUEUED,
            stage="queued",
            progress_percent=0,
            error_code=None,
            error_message=None,
        )
        runtime.repository.update_separation_job(queued)
        _schedule_separation(background, runtime, queued.job_id)
        return _separation_response(queued)

    @app.get("/api/songs/{song_id}/stems", response_model=list[StemResponse])
    def list_stems(
        song_id: str, runtime: ApiServices = Depends(get_services)
    ) -> list[StemResponse]:
        runtime.repository.get_song(runtime.owner_id, song_id)
        stems = runtime.repository.list_stems(runtime.owner_id, song_id)
        return [_stem_response(stem) for stem in stems]

    @app.post("/api/stems/{stem_id}/tabs", response_model=TabResponse, status_code=201)
    def create_tab(
        stem_id: str,
        payload: TabCreateRequest,
        background: BackgroundTasks,
        runtime: ApiServices = Depends(get_services),
    ) -> TabResponse:
        stem = runtime.repository.get_stem(runtime.owner_id, stem_id)
        if not stem.tab_eligible:
            _api_error(
                422,
                "UNSUPPORTED_STEM",
                "Only acoustic-guitar and electric-guitar stems support TAB",
            )
        options = TabOptions(**payload.model_dump())
        tab = Tab(
            tab_id=str(uuid4()),
            job_id=str(uuid4()),
            song_id=stem.song_id,
            stem_id=stem.stem_id,
            owner_id=runtime.owner_id,
            options=options,
        )
        tab = runtime.repository.create_tab(tab)
        _schedule_tab(background, runtime, tab.tab_id)
        return _tab_response(tab)

    @app.get("/api/tabs", response_model=list[TabResponse])
    def list_tabs(
        status: JobStatus | None = None,
        runtime: ApiServices = Depends(get_services),
    ) -> list[TabResponse]:
        tabs = runtime.repository.list_tabs(runtime.owner_id, status=status)
        return [_tab_response(tab) for tab in tabs]

    @app.get("/api/tabs/{tab_id}", response_model=TabResponse)
    def get_tab(
        tab_id: str, runtime: ApiServices = Depends(get_services)
    ) -> TabResponse:
        return _tab_response(runtime.repository.get_tab(runtime.owner_id, tab_id))

    @app.post("/api/tabs/{tab_id}/retry", response_model=TabResponse)
    def retry_tab(
        tab_id: str,
        background: BackgroundTasks,
        runtime: ApiServices = Depends(get_services),
    ) -> TabResponse:
        tab = runtime.repository.get_tab(runtime.owner_id, tab_id)
        if tab.status is not JobStatus.FAILED:
            _api_error(409, "JOB_NOT_FAILED", "Only failed TAB jobs can be retried")
        queued = replace(
            tab,
            status=JobStatus.QUEUED,
            stage="queued",
            progress_percent=0,
            error_code=None,
            error_message=None,
        )
        runtime.repository.update_tab(queued)
        _schedule_tab(background, runtime, queued.tab_id)
        return _tab_response(queued)

    @app.get("/api/files/{key:path}")
    def get_artifact(
        key: str, runtime: ApiServices = Depends(get_services)
    ) -> FileResponse:
        validate_artifact_key(key)
        parts = key.split("/")
        if len(parts) < 3 or parts[0] != "songs":
            _api_error(404, "ARTIFACT_NOT_FOUND", "Artifact not found")
        runtime.repository.get_song(runtime.owner_id, parts[1])
        return FileResponse(runtime.artifacts.materialize(key))

    static_dir = Path(os.environ.get("FRETFLOW_STATIC_DIR", "/app/static"))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app


def _create_default_services() -> ApiServices:
    settings = Settings.from_env()
    repository = SqlAlchemyJobRepository(
        create_session_factory(create_database_engine(settings.database_url))
    )
    return ApiServices(
        repository=repository,
        artifacts=LocalArtifactStore(settings.artifact_root),
        owner_id=settings.owner_id,
        pipeline=create_pipeline(settings),
        execute_jobs=True,
    )


def _schedule_separation(
    background: BackgroundTasks, runtime: ApiServices, job_id: str
) -> None:
    if runtime.execute_jobs and runtime.pipeline is not None:
        background.add_task(
            _ignore_job_error,
            runtime.pipeline.run_separation,
            runtime.owner_id,
            job_id,
        )


def _schedule_tab(background: BackgroundTasks, runtime: ApiServices, tab_id: str) -> None:
    if runtime.execute_jobs and runtime.pipeline is not None:
        background.add_task(
            _ignore_job_error, runtime.pipeline.run_tab, runtime.owner_id, tab_id
        )


def _ignore_job_error(function: Any, *args: Any) -> None:
    try:
        function(*args)
    except Exception:
        return


def _api_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": {}},
    )


def _song_response(song: Song) -> SongResponse:
    return SongResponse(
        song_id=song.song_id,
        title=song.title,
        source_filename=song.source_filename,
        source_artifact_key=song.source_artifact_key,
        duration_seconds=song.duration_seconds,
        media_type=song.media_type,
        sha256=song.sha256,
        status=song.status.value,
        created_at=song.created_at,
        updated_at=song.updated_at,
    )


def _separation_response(job: SeparationJob) -> SeparationResponse:
    return SeparationResponse(
        job_id=job.job_id,
        song_id=job.song_id,
        requested_stems=[stem.value for stem in job.requested_stems],
        auto_tab_stems=[stem.value for stem in job.auto_tab_stems],
        status=job.status.value,
        stage=job.stage,
        progress_percent=job.progress_percent,
        started_at=job.started_at,
        finished_at=job.finished_at,
        elapsed_seconds=job.elapsed_seconds,
        error_code=job.error_code,
        error_message=job.error_message,
        diagnostics=job.diagnostics,
    )


def _stem_response(stem: Stem) -> StemResponse:
    return StemResponse(
        stem_id=stem.stem_id,
        song_id=stem.song_id,
        separation_job_id=stem.separation_job_id,
        stem_type=stem.stem_type.value,
        status=stem.status.value,
        tab_eligible=stem.tab_eligible,
        duration_seconds=stem.duration_seconds,
        sample_rate=stem.sample_rate,
        channels=stem.channels,
        artifact_url=f"/api/files/{stem.artifact_key}",
    )


def _tab_response(tab: Tab) -> TabResponse:
    return TabResponse(
        tab_id=tab.tab_id,
        job_id=tab.job_id,
        song_id=tab.song_id,
        stem_id=tab.stem_id,
        status=tab.status.value,
        stage=tab.stage,
        progress_percent=tab.progress_percent,
        tuning=tab.options.tuning,
        capo=tab.options.capo,
        max_fret=tab.options.max_fret,
        max_stretch=tab.options.max_stretch,
        event_count=tab.event_count,
        dropped_note_count=tab.dropped_note_count,
        midi_url=f"/api/files/{tab.midi_artifact_key}" if tab.midi_artifact_key else None,
        tab_url=f"/api/files/{tab.tab_artifact_key}" if tab.tab_artifact_key else None,
        model_output_url=(
            f"/api/files/{tab.model_output_artifact_key}"
            if tab.model_output_artifact_key
            else None
        ),
        started_at=tab.started_at,
        finished_at=tab.finished_at,
        elapsed_seconds=tab.elapsed_seconds,
        error_code=tab.error_code,
        error_message=tab.error_message,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


app = create_app()
