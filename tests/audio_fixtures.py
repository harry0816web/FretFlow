"""Tiny, real, decodable audio for tests (no committed binary fixtures)."""

import io
import math
import struct
import wave


def wav_bytes(seconds: float = 0.5, sample_rate: int = 22050, channels: int = 1) -> bytes:
    frames = int(seconds * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        samples = (
            int(16000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            for index in range(frames)
        )
        handle.writeframes(
            b"".join(struct.pack("<h", value) * channels for value in samples)
        )
    return buffer.getvalue()
