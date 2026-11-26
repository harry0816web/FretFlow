import pytest

from fretflow.gpu_preflight import PreflightError, validate_runtime


def runtime_info(**overrides):
    payload = {
        "python": "3.10.19",
        "torch": "2.11.0+cu130",
        "torch_cuda": "13.0",
        "msst": "0.1.0",
        "basic_pitch": "0.4.0",
        "ffmpeg": "/usr/bin/ffmpeg",
        "cuda_available": True,
        "gpu": "NVIDIA L4",
    }
    payload.update(overrides)
    return payload


def test_gpu_preflight_accepts_pinned_runtime():
    validate_runtime(runtime_info(), require_gpu=True)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"python": "3.11.14"}, "Python 3.10"),
        ({"torch": "2.12.0+cu130"}, "torch 2.11.0"),
        ({"cuda_available": False}, "CUDA is not available"),
        ({"ffmpeg": None}, "FFmpeg"),
    ],
)
def test_gpu_preflight_rejects_runtime_drift(overrides, message):
    with pytest.raises(PreflightError, match=message):
        validate_runtime(runtime_info(**overrides), require_gpu=True)
