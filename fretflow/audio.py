"""Audio inspection: validate uploads with ffprobe, describe WAV stems."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

PROBE_TIMEOUT_SECONDS = 30
_PEAK_BLOCK_FRAMES = 1 << 16


class InvalidAudioError(ValueError):
    """Raised when a file cannot be decoded as audio."""


@dataclass(frozen=True, slots=True)
class AudioProbe:
    duration_seconds: float
    sample_rate: int | None
    channels: int | None
    codec: str | None


@dataclass(frozen=True, slots=True)
class WavInfo:
    sample_rate: int
    channels: int
    frames: int
    subtype: str
    duration_seconds: float
    peak: float


Runner = Callable[..., subprocess.CompletedProcess[str]]


def probe_audio(path: Path, *, runner: Runner = subprocess.run) -> AudioProbe:
    """Return the first audio stream's facts, or raise InvalidAudioError."""

    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError("ffprobe is not installed; install FFmpeg")
    try:
        completed = runner(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise InvalidAudioError("Timed out while reading the audio file") from error
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        message = detail[-1] if detail else "File is not decodable audio"
        # ffprobe prefixes the server-side path; never echo it to clients.
        raise InvalidAudioError(message.replace(f"{path}: ", "").replace(str(path), "file"))
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as error:
        raise InvalidAudioError("ffprobe returned unreadable output") from error

    streams = payload.get("streams") or []
    if not streams:
        raise InvalidAudioError("File contains no audio stream")
    stream = streams[0]
    duration = _positive_float(stream.get("duration")) or _positive_float(
        (payload.get("format") or {}).get("duration")
    )
    if duration is None:
        raise InvalidAudioError("Audio duration is unknown or zero")
    return AudioProbe(
        duration_seconds=duration,
        sample_rate=_positive_int(stream.get("sample_rate")),
        channels=_positive_int(stream.get("channels")),
        codec=stream.get("codec_name"),
    )


def read_wav_info(path: Path) -> WavInfo:
    """Describe a separated stem, including its absolute peak sample."""

    import numpy as np
    import soundfile as sf

    try:
        info = sf.info(str(path))
        peak = 0.0
        with sf.SoundFile(str(path)) as handle:
            for block in handle.blocks(blocksize=_PEAK_BLOCK_FRAMES, dtype="float32"):
                if block.size:
                    peak = max(peak, float(np.max(np.abs(block))))
    except (RuntimeError, sf.LibsndfileError) as error:
        raise InvalidAudioError(f"Cannot read stem audio: {error}") from error
    return WavInfo(
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        frames=int(info.frames),
        subtype=str(info.subtype),
        duration_seconds=float(info.frames) / float(info.samplerate),
        peak=peak,
    )


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
