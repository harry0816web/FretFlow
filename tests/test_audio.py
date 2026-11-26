import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from fretflow.audio import InvalidAudioError, probe_audio, read_wav_info
from tests.audio_fixtures import wav_bytes


def test_probe_reads_duration_and_format_of_real_audio(tmp_path: Path):
    path = tmp_path / "tone.wav"
    path.write_bytes(wav_bytes(seconds=1.0, sample_rate=44100, channels=2))

    probe = probe_audio(path)

    assert probe.duration_seconds == pytest.approx(1.0)
    assert probe.sample_rate == 44100
    assert probe.channels == 2
    assert probe.codec == "pcm_s16le"


def test_probe_rejects_text_files(tmp_path: Path):
    path = tmp_path / "notes.mp3"
    path.write_text("not audio at all", encoding="utf-8")

    with pytest.raises(InvalidAudioError) as error:
        probe_audio(path)
    assert str(tmp_path) not in str(error.value)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"streams": []}, "no audio stream"),
        ({"streams": [{"codec_name": "aac"}], "format": {"duration": "0"}}, "duration"),
    ],
)
def test_probe_rejects_streamless_or_zero_length_output(tmp_path, payload, message):
    def runner(command, **_):
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    with pytest.raises(InvalidAudioError, match=message):
        probe_audio(tmp_path / "x.mp3", runner=runner)


def test_probe_falls_back_to_container_duration(tmp_path: Path):
    payload = {
        "streams": [{"codec_name": "mp3", "sample_rate": "48000", "channels": 2}],
        "format": {"duration": "212.5"},
    }

    def runner(command, **_):
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    probe = probe_audio(tmp_path / "x.mp3", runner=runner)
    assert probe.duration_seconds == 212.5
    assert probe.sample_rate == 48000


def test_read_wav_info_reports_float_stem_metadata_and_peak(tmp_path: Path):
    path = tmp_path / "stem.wav"
    audio = np.zeros((44100, 2), dtype=np.float32)
    audio[100, 1] = -0.75
    sf.write(path, audio, 44100, subtype="FLOAT")

    info = read_wav_info(path)

    assert (info.sample_rate, info.channels, info.frames) == (44100, 2, 44100)
    assert info.subtype == "FLOAT"
    assert info.duration_seconds == pytest.approx(1.0)
    assert info.peak == pytest.approx(0.75)


def test_read_wav_info_rejects_unreadable_files(tmp_path: Path):
    path = tmp_path / "broken.wav"
    path.write_bytes(b"RIFF....")

    with pytest.raises(InvalidAudioError):
        read_wav_info(path)
