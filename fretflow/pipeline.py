"""Idempotent orchestration for separation and guitar TAB jobs."""

from __future__ import annotations

import tempfile
import time
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid5

from fretflow.artifacts import ArtifactStore
from fretflow.domain import (
    ArtifactStatus,
    JobStatus,
    SongStatus,
    Stem,
    StemType,
    Tab,
    TabOptions,
    utc_now,
)
from fretflow.progress import ProgressEvent
from fretflow.repository import JobRepository, tab_options_fingerprint
from fretflow.services.contracts import StemSeparator, TabTranscriber


class Pipeline:
    def __init__(
        self,
        *,
        repository: JobRepository,
        artifacts: ArtifactStore,
        separator: StemSeparator,
        transcriber: TabTranscriber,
        work_root: Path,
    ) -> None:
        self._repository = repository
        self._artifacts = artifacts
        self._separator = separator
        self._transcriber = transcriber
        self._work_root = work_root.expanduser().resolve()
        self._work_root.mkdir(parents=True, exist_ok=True)

    def run_separation(self, owner_id: str, job_id: str) -> list[Stem]:
        job = self._repository.get_separation_job(owner_id, job_id)
        song = self._repository.get_song(owner_id, job.song_id)
        if job.status is JobStatus.SUCCEEDED:
            return self._repository.list_stems(owner_id, song.song_id)
        if job.status is JobStatus.FAILED:
            job = replace(
                job,
                status=JobStatus.QUEUED,
                stage="queued",
                progress_percent=0,
                error_code=None,
                error_message=None,
            )
            self._repository.update_separation_job(job)

        started_at = utc_now()
        started_clock = time.perf_counter()
        job = replace(
            job,
            status=JobStatus.RUNNING,
            stage="preparing",
            progress_percent=1,
            started_at=started_at,
            finished_at=None,
        )
        self._repository.update_separation_job(job)
        self._repository.update_song(
            replace(song, status=SongStatus.SEPARATING, updated_at=utc_now())
        )

        def progress(event: ProgressEvent) -> None:
            nonlocal job
            job = replace(
                job,
                stage=event.stage,
                progress_percent=min(event.progress_percent, 99),
            )
            self._repository.update_separation_job(job)

        try:
            source = self._artifacts.materialize(song.source_artifact_key)
            with tempfile.TemporaryDirectory(
                prefix=f"separation-{job.job_id}-", dir=self._work_root
            ) as temporary:
                result = self._separator.separate(
                    source,
                    job.requested_stems,
                    Path(temporary),
                    progress,
                )
                stems = []
                for stem_type in job.requested_stems:
                    output_path = result.stems[stem_type]
                    suffix = output_path.suffix.lower() or ".wav"
                    artifact_key = (
                        f"songs/{song.song_id}/separations/{job.job_id}/stems/"
                        f"{stem_type.value}{suffix}"
                    )
                    self._artifacts.put_file(output_path, artifact_key, overwrite=True)
                    stem_id = str(uuid5(UUID(job.job_id), stem_type.value))
                    stem = Stem(
                        stem_id=stem_id,
                        song_id=song.song_id,
                        separation_job_id=job.job_id,
                        owner_id=owner_id,
                        stem_type=stem_type,
                        artifact_key=artifact_key,
                        status=ArtifactStatus.READY,
                    )
                    stems.append(self._repository.create_stem(stem))
                manifest_key = (
                    f"songs/{song.song_id}/separations/{job.job_id}/manifest.json"
                )
                self._artifacts.put_file(
                    result.manifest_path, manifest_key, overwrite=True
                )

            finished_at = utc_now()
            job = replace(
                job,
                status=JobStatus.SUCCEEDED,
                stage="complete",
                progress_percent=100,
                finished_at=finished_at,
                elapsed_seconds=time.perf_counter() - started_clock,
                diagnostics={**job.diagnostics, **result.diagnostics},
            )
            self._repository.update_separation_job(job)

            tab_failed = False
            for stem in stems:
                if stem.stem_type not in job.auto_tab_stems:
                    continue
                tab = self._create_auto_tab(stem)
                try:
                    self.run_tab(owner_id, tab.tab_id)
                except Exception:
                    tab_failed = True
            final_status = SongStatus.PARTIAL_FAILED if tab_failed else SongStatus.READY
            self._repository.update_song(
                replace(song, status=final_status, updated_at=utc_now())
            )
            return stems
        except Exception as error:
            failed = replace(
                job,
                status=JobStatus.FAILED,
                stage="failed",
                finished_at=utc_now(),
                elapsed_seconds=time.perf_counter() - started_clock,
                error_code=type(error).__name__.upper(),
                error_message=str(error),
            )
            self._repository.update_separation_job(failed)
            self._repository.update_song(
                replace(song, status=SongStatus.FAILED, updated_at=utc_now())
            )
            raise

    def run_tab(self, owner_id: str, tab_id: str) -> Tab:
        tab = self._repository.get_tab(owner_id, tab_id)
        if tab.status is JobStatus.SUCCEEDED:
            return tab
        if tab.status is JobStatus.FAILED:
            tab = replace(
                tab,
                status=JobStatus.QUEUED,
                stage="queued",
                progress_percent=0,
                error_code=None,
                error_message=None,
            )
            self._repository.update_tab(tab)
        stem = self._repository.get_stem(owner_id, tab.stem_id)
        started_clock = time.perf_counter()
        tab = replace(
            tab,
            status=JobStatus.RUNNING,
            stage="preparing",
            progress_percent=1,
            started_at=utc_now(),
            finished_at=None,
        )
        self._repository.update_tab(tab)

        def progress(event: ProgressEvent) -> None:
            nonlocal tab
            tab = replace(
                tab,
                stage=event.stage,
                progress_percent=min(event.progress_percent, 99),
            )
            self._repository.update_tab(tab)

        try:
            source = self._artifacts.materialize(stem.artifact_key)
            with tempfile.TemporaryDirectory(
                prefix=f"tab-{tab.tab_id}-", dir=self._work_root
            ) as temporary:
                result = self._transcriber.transcribe(
                    source, tab.options, Path(temporary), progress
                )
                prefix = f"songs/{tab.song_id}/tabs/{tab.tab_id}"
                midi_key = f"{prefix}/transcription.mid"
                tab_key = f"{prefix}/transcription.tab.json"
                self._artifacts.put_file(result.midi_path, midi_key, overwrite=True)
                self._artifacts.put_file(result.tab_path, tab_key, overwrite=True)
                model_key = None
                if result.model_output_path is not None:
                    model_key = f"{prefix}/model-output.npz"
                    self._artifacts.put_file(
                        result.model_output_path, model_key, overwrite=True
                    )
            tab = replace(
                tab,
                status=JobStatus.SUCCEEDED,
                stage="complete",
                progress_percent=100,
                midi_artifact_key=midi_key,
                tab_artifact_key=tab_key,
                model_output_artifact_key=model_key,
                event_count=result.event_count,
                dropped_note_count=result.dropped_note_count,
                finished_at=utc_now(),
                elapsed_seconds=time.perf_counter() - started_clock,
                diagnostics={**tab.diagnostics, **result.diagnostics},
            )
            self._repository.update_tab(tab)
            return tab
        except Exception as error:
            failed = replace(
                tab,
                status=JobStatus.FAILED,
                stage="failed",
                finished_at=utc_now(),
                elapsed_seconds=time.perf_counter() - started_clock,
                error_code=type(error).__name__.upper(),
                error_message=str(error),
            )
            self._repository.update_tab(failed)
            raise

    def _create_auto_tab(self, stem: Stem) -> Tab:
        options = TabOptions()
        fingerprint = tab_options_fingerprint(options)
        tab_id = str(uuid5(UUID(stem.stem_id), fingerprint))
        tab = Tab(
            tab_id=tab_id,
            job_id=str(uuid5(UUID(tab_id), "job")),
            song_id=stem.song_id,
            stem_id=stem.stem_id,
            owner_id=stem.owner_id,
            options=options,
        )
        return self._repository.create_tab(tab)
