"""Validate a worker image's runtime before it accepts inference jobs.

``cuda`` checks the pinned NVIDIA image; ``cpu`` checks the CPU fallback image.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import shutil
from pathlib import Path
from typing import Any

from download_mvsep_mega import ASSETS, verify_asset


class PreflightError(RuntimeError):
    """Raised when the GPU worker runtime is not safe to use."""


BACKENDS = ("cuda", "cpu")


def validate_runtime(
    info: dict[str, Any], *, require_gpu: bool, backend: str = "cuda"
) -> None:
    if backend not in BACKENDS:
        raise PreflightError(f"Unknown worker backend: {backend}")
    if not str(info.get("python", "")).startswith("3.10."):
        raise PreflightError(f"Python 3.10 is required, found {info.get('python')}")
    torch_version = str(info.get("torch", ""))
    if backend == "cuda":
        if torch_version != "2.11.0+cu130":
            raise PreflightError(
                f"torch 2.11.0+cu130 is required, found {info.get('torch')}"
            )
        if str(info.get("torch_cuda", "")) != "13.0":
            raise PreflightError(
                f"CUDA 13.0 runtime is required, found {info.get('torch_cuda')}"
            )
    elif torch_version.split("+", 1)[0] != "2.11.0":
        raise PreflightError(f"torch 2.11.0 is required, found {info.get('torch')}")
    if str(info.get("msst", "")) != "0.1.0":
        raise PreflightError(f"msst 0.1.0 is required, found {info.get('msst')}")
    if not str(info.get("basic_pitch", "")).startswith("0.4."):
        raise PreflightError(
            f"basic-pitch 0.4.x is required, found {info.get('basic_pitch')}"
        )
    if not info.get("ffmpeg"):
        raise PreflightError("FFmpeg is not available")
    if require_gpu and not info.get("cuda_available"):
        raise PreflightError("CUDA is not available to the container")
    if require_gpu and not info.get("gpu"):
        raise PreflightError("CUDA reported available but no GPU name was returned")


def inspect_runtime() -> dict[str, Any]:
    try:
        import torch
    except ImportError as error:
        raise PreflightError("torch is not installed") from error
    cuda_available = bool(torch.cuda.is_available())
    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "msst": importlib.metadata.version("msst"),
        "basic_pitch": importlib.metadata.version("basic-pitch"),
        "ffmpeg": shutil.which("ffmpeg"),
        "cuda_available": cuda_available,
        "gpu": torch.cuda.get_device_name(0) if cuda_available else None,
        "compute_capability": (
            ".".join(map(str, torch.cuda.get_device_capability(0)))
            if cuda_available
            else None
        ),
    }


def verify_models(model_dir: Path) -> list[dict[str, Any]]:
    root = model_dir.expanduser().resolve()
    results = []
    for asset in ASSETS:
        path = root / asset.filename
        if not verify_asset(path, asset, quiet=True):
            raise PreflightError(f"Model asset failed verification: {path}")
        results.append(
            {
                "filename": asset.filename,
                "size": asset.size,
                "sha256": asset.sha256,
            }
        )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the FretFlow GPU worker")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("/opt/fretflow/models/mvsep_mega"),
    )
    parser.add_argument("--backend", choices=BACKENDS, default="cuda")
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--skip-model", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runtime = inspect_runtime()
        if args.require_gpu and args.backend != "cuda":
            raise PreflightError("--require-gpu needs --backend cuda")
        validate_runtime(runtime, require_gpu=args.require_gpu, backend=args.backend)
        models = [] if args.skip_model else verify_models(args.model_dir)
    except (PreflightError, importlib.metadata.PackageNotFoundError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
    print(json.dumps({"status": "ok", "runtime": runtime, "models": models}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
