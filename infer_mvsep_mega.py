#!/usr/bin/env python3
"""Run MVSep Mega v1.0.21 for selected stems on one NVIDIA GPU.

The official checkpoint contains 53 output heads. This runner first loads the
complete checkpoint strictly on CPU, then retains only the requested independent
mask heads before moving the model to CUDA. The shared BS-RoFormer backbone is
unchanged.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MODEL_VERSION = "v1.0.21"
MODEL_COMMIT = "ea7eb9c20ea0e3f94368a30fc1654b51cdd55789"
CONFIG_FILENAME = "mvsep_mega_model_bs_roformer_53_stems.yaml"
CHECKPOINT_FILENAME = "mvsep_mega_model_bs_roformer_53_stems_v1.ckpt"
CONFIG_SIZE = 4_184
CHECKPOINT_SIZE = 1_368_919_887
CONFIG_SHA256 = "7e198062a251587088adb91215a4f44ab59e67bd62fcc805cf54d6e7dfc51103"
CHECKPOINT_SHA256 = "c62820893bbf86d4e734f966bd142d9157cfc8bb8e79e9d8f9ea553f3ff3519f"
DEFAULT_STEMS = ("acoustic-guitar", "electric-guitar")
SUPPORTED_AUDIO_SUFFIXES = {
    ".wav",
    ".wave",
    ".flac",
    ".mp3",
    ".ogg",
    ".oga",
    ".opus",
    ".aif",
    ".aiff",
}
HASH_BUFFER_SIZE = 8 * 1024 * 1024

# Loaded lazily so `--help` works before workstation dependencies are installed.
np: Any = None
torch: Any = None
sf: Any = None
librosa: Any = None
yaml: Any = None
tqdm: Any = None
BSRoformer: Any = None


def load_runtime_dependencies() -> None:
    global np, torch, sf, librosa, yaml, tqdm, BSRoformer
    try:
        import librosa as _librosa
        import numpy as _np
        import soundfile as _sf
        import torch as _torch
        import yaml as _yaml
        from msst.models.bs_roformer import BSRoformer as _BSRoformer
        from tqdm.auto import tqdm as _tqdm
    except ImportError as error:
        raise RuntimeError(
            "Missing MVSep inference dependencies. Run: "
            "python -m pip install --upgrade-strategy only-if-needed "
            "-r requirements-mvsep.txt"
        ) from error
    np = _np
    torch = _torch
    sf = _sf
    librosa = _librosa
    yaml = _yaml
    tqdm = _tqdm
    BSRoformer = _BSRoformer


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(HASH_BUFFER_SIZE):
            digest.update(block)
    return digest.hexdigest()


def verify_asset(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    skip_checksum: bool,
) -> None:
    if not path.is_file():
        raise FileNotFoundError(
            f"Model asset not found: {path}. Run python3 download_mvsep_mega.py first."
        )
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise RuntimeError(
            f"Unexpected size for {path}: expected {expected_size}, got {actual_size}. "
            "Download the asset again."
        )
    if skip_checksum:
        return
    print(f"Verifying SHA-256: {path.name}")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"SHA-256 mismatch for {path}: expected {expected_sha256}, "
            f"got {actual_sha256}"
        )


def collect_inputs(
    raw_inputs: Iterable[str],
    *,
    exclude_root: Path | None = None,
) -> list[Path]:
    exclude_root = exclude_root.resolve() if exclude_root is not None else None

    def excluded(candidate: Path) -> bool:
        return exclude_root is not None and candidate.is_relative_to(exclude_root)

    files: list[Path] = []
    for raw in raw_inputs:
        path = Path(raw).expanduser().resolve()
        if path.is_file():
            if path.suffix.lower() not in SUPPORTED_AUDIO_SUFFIXES:
                raise ValueError(f"Unsupported audio extension: {path}")
            if not excluded(path):
                files.append(path)
        elif path.is_dir():
            files.extend(
                candidate
                for candidate in sorted(path.rglob("*"))
                if candidate.is_file()
                and candidate.suffix.lower() in SUPPORTED_AUDIO_SUFFIXES
                and not excluded(candidate)
            )
        else:
            raise FileNotFoundError(f"Input path does not exist: {path}")

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    if not unique:
        raise ValueError("No supported audio files were found.")
    return unique


def parse_device(raw: str) -> Any:
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA is not available in this Python environment. Verify with: "
            "python -c 'import torch; print(torch.cuda.is_available())'"
        )
    device = torch.device(raw)
    if device.type != "cuda":
        raise ValueError("MVSep Mega inference requires a CUDA device such as cuda:0.")
    index = device.index if device.index is not None else torch.cuda.current_device()
    if index < 0 or index >= torch.cuda.device_count():
        raise ValueError(
            f"CUDA device {index} is unavailable; detected {torch.cuda.device_count()} GPU(s)."
        )
    torch.cuda.set_device(index)
    return torch.device(f"cuda:{index}")


def runtime_info(device: Any) -> dict[str, Any]:
    index = device.index
    properties = torch.cuda.get_device_properties(index)
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "msst": importlib.metadata.version("msst"),
        "device": str(device),
        "gpu": properties.name,
        "compute_capability": f"{properties.major}.{properties.minor}",
        "gpu_total_memory_bytes": properties.total_memory,
    }


def print_environment(info: dict[str, Any]) -> None:
    gib = info["gpu_total_memory_bytes"] / (1024**3)
    print(
        f"GPU: {info['gpu']} ({info['device']}, compute capability "
        f"{info['compute_capability']}, {gib:.1f} GiB)"
    )
    print(
        f"Runtime: Python {info['python']}, torch {info['torch']}, "
        f"CUDA {info['torch_cuda']}, msst {info['msst']}"
    )


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.load(handle, Loader=yaml.FullLoader)
    if not isinstance(config, dict):
        raise TypeError(f"Invalid YAML configuration: {path}")
    for section in ("audio", "model", "training", "inference"):
        if not isinstance(config.get(section), dict):
            raise TypeError(f"Configuration is missing section: {section}")
    return config


def validate_config(config: dict[str, Any], stems: list[str]) -> tuple[list[int], int]:
    instruments = config["training"].get("instruments")
    if not isinstance(instruments, list) or len(instruments) != 53:
        raise RuntimeError(
            "Expected the official 53-stem MVSep Mega configuration; "
            f"found {len(instruments) if isinstance(instruments, list) else 'invalid'} stems."
        )
    if config["model"].get("num_stems") != len(instruments):
        raise RuntimeError("model.num_stems does not match training.instruments.")
    if config["audio"].get("sample_rate") != 44_100:
        raise RuntimeError("Expected the official 44.1 kHz MVSep Mega configuration.")
    if config["audio"].get("num_channels") != 2:
        raise RuntimeError("Expected the official stereo MVSep Mega configuration.")

    duplicates = sorted({stem for stem in stems if stems.count(stem) > 1})
    if duplicates:
        raise ValueError(f"Duplicate requested stems: {', '.join(duplicates)}")
    missing = [stem for stem in stems if stem not in instruments]
    if missing:
        raise ValueError(
            f"Unknown stems: {', '.join(missing)}. Available stems: "
            + ", ".join(instruments)
        )
    return [instruments.index(stem) for stem in stems], config["audio"]["sample_rate"]


def extract_state_dict(checkpoint: Any) -> dict[str, Any]:
    state = checkpoint
    for key in ("state", "state_dict", "model_state_dict"):
        if isinstance(state, dict) and key in state and isinstance(state[key], dict):
            state = state[key]
    if not isinstance(state, dict) or not state:
        raise RuntimeError("Checkpoint does not contain a model state dict.")
    if all(isinstance(key, str) and key.startswith("module.") for key in state):
        state = {key.removeprefix("module."): value for key, value in state.items()}
    return state


def load_model(
    config: dict[str, Any],
    checkpoint_path: Path,
    selected_indices: list[int],
    device: Any,
) -> tuple[Any, float]:
    started = time.monotonic()
    print("Constructing the official 53-head BS-RoFormer on CPU ...")
    model = BSRoformer(**config["model"])
    print(f"Loading checkpoint: {checkpoint_path}")
    checkpoint = torch.load(
        checkpoint_path,
        map_location="cpu",
        weights_only=False,
    )
    state = extract_state_dict(checkpoint)
    model.load_state_dict(state, strict=True)

    # Each stem has an independent mask estimator after the shared backbone.
    # Prune only after a strict full-checkpoint load, preserving the selected
    # modules exactly while avoiding transfer of the other 51 heads to CUDA.
    selected_heads = [model.mask_estimators[index] for index in selected_indices]
    model.mask_estimators = torch.nn.ModuleList(selected_heads)
    model.num_stems = len(selected_heads)

    del state, checkpoint, selected_heads
    gc.collect()
    model.eval().to(device)
    torch.cuda.synchronize(device)
    elapsed = time.monotonic() - started
    print(
        f"Model loaded and pruned to {len(selected_indices)} head(s) in {elapsed:.2f}s"
    )
    return model, elapsed


def load_audio(path: Path, sample_rate: int) -> Any:
    try:
        audio, _ = librosa.load(
            path,
            sr=sample_rate,
            mono=False,
            dtype=np.float32,
        )
    except Exception as error:
        raise RuntimeError(f"Cannot decode {path}: {error}") from error
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 1:
        audio = np.stack((audio, audio), axis=0)
    if audio.ndim != 2 or audio.shape[0] != 2:
        raise RuntimeError(
            f"Expected mono or stereo audio, got shape {audio.shape} for {path}."
        )
    if audio.shape[1] == 0:
        raise RuntimeError(f"Decoded audio is empty: {path}")
    if not np.isfinite(audio).all():
        raise RuntimeError(f"Input contains NaN or Inf values: {path}")
    return np.ascontiguousarray(audio)


def linear_window(size: int, fade_size: int) -> Any:
    window = np.ones(size, dtype=np.float32)
    if fade_size > 0:
        window[:fade_size] = np.linspace(0, 1, fade_size, dtype=np.float32)
        window[-fade_size:] = np.linspace(1, 0, fade_size, dtype=np.float32)
    return window


def separate_selected_stems(
    model: Any,
    audio: Any,
    *,
    device: Any,
    chunk_size: int,
    overlap: int,
    precision: str,
    stem_count: int,
) -> Any:
    if overlap < 2:
        raise ValueError("Overlap must be at least 2.")
    step = chunk_size // overlap
    if step < 1:
        raise ValueError("Chunk size is too small for the selected overlap.")

    border = chunk_size - step
    original_length = audio.shape[-1]
    padded = original_length > 2 * border and border > 0
    if padded:
        work_audio = np.pad(audio, ((0, 0), (border, border)), mode="reflect")
    else:
        work_audio = audio

    total_length = work_audio.shape[-1]
    result = np.zeros((stem_count, 2, total_length), dtype=np.float32)
    counter = np.zeros(total_length, dtype=np.float32)
    fade_size = chunk_size // 10
    base_window = linear_window(chunk_size, fade_size)
    starts = range(0, total_length, step)
    total_chunks = math.ceil(total_length / step)

    autocast_enabled = precision != "fp32"
    autocast_dtype = torch.float16 if precision == "fp16" else torch.bfloat16
    with (
        torch.inference_mode(),
        tqdm(total=total_chunks, desc="Separating", unit="chunk") as progress,
    ):
        for start in starts:
            segment = work_audio[:, start : start + chunk_size]
            segment_length = segment.shape[-1]
            tensor = torch.from_numpy(np.ascontiguousarray(segment)).to(device)
            if segment_length < chunk_size:
                pad_amount = chunk_size - segment_length
                if segment_length > chunk_size // 2:
                    tensor = torch.nn.functional.pad(
                        tensor, (0, pad_amount), mode="reflect"
                    )
                else:
                    tensor = torch.nn.functional.pad(
                        tensor, (0, pad_amount), mode="constant"
                    )
            tensor = tensor.unsqueeze(0)

            with torch.autocast(
                device_type="cuda",
                dtype=autocast_dtype,
                enabled=autocast_enabled,
            ):
                estimates = model(tensor)
            estimates = estimates[0, :, :, :segment_length].float().cpu().numpy()

            # Match the upstream overlap-add order: modify the full-size window
            # first, then crop it to the unpadded segment length.
            window = base_window.copy()
            if start == 0 and fade_size > 0:
                window[:fade_size] = 1
            if start + step >= total_length and fade_size > 0:
                window[-fade_size:] = 1
            window = window[:segment_length]
            result[:, :, start : start + segment_length] += estimates * window
            counter[start : start + segment_length] += window
            del tensor, estimates
            progress.update(1)

    if np.any(counter <= 0):
        raise RuntimeError("Overlap-add produced uncovered output samples.")
    result /= counter[None, None, :]
    if padded:
        result = result[..., border:-border]
    result = result[..., :original_length]
    np.nan_to_num(result, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return result


def output_folder_for(input_path: Path, output_root: Path) -> Path:
    return output_root / input_path.stem


def write_wav_atomic(path: Path, audio: Any, sample_rate: int, subtype: str) -> None:
    temporary = path.with_name(f".{path.name}.part")
    sf.write(
        temporary,
        audio.T,
        sample_rate,
        format="WAV",
        subtype=subtype,
    )
    temporary.replace(path)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.part")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def process_file(
    input_path: Path,
    *,
    model: Any,
    output_root: Path,
    stems: list[str],
    sample_rate: int,
    chunk_size: int,
    overlap: int,
    precision: str,
    subtype: str,
    overwrite: bool,
    device: Any,
    environment: dict[str, Any],
    config_path: Path,
    checkpoint_path: Path,
    checksums_verified: bool,
    model_load_seconds: float,
) -> Path:
    destination = output_folder_for(input_path, output_root)
    output_paths = [destination / f"{stem}.wav" for stem in stems]
    manifest_path = destination / "manifest.json"
    existing = [path for path in (*output_paths, manifest_path) if path.exists()]
    if existing and not overwrite:
        raise FileExistsError(
            f"Output already exists for {input_path}: {existing[0]}. "
            "Use --overwrite to replace this song's outputs."
        )
    destination.mkdir(parents=True, exist_ok=True)

    print(f"\nInput: {input_path}")
    audio = load_audio(input_path, sample_rate)
    duration_seconds = audio.shape[-1] / sample_rate
    print(
        f"Decoded: {duration_seconds:.2f}s, {sample_rate} Hz, stereo; "
        f"chunk={chunk_size / sample_rate:.2f}s, overlap={overlap}, precision={precision}"
    )

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    torch.cuda.synchronize(device)
    started = time.monotonic()
    try:
        separated = separate_selected_stems(
            model,
            audio,
            device=device,
            chunk_size=chunk_size,
            overlap=overlap,
            precision=precision,
            stem_count=len(stems),
        )
        torch.cuda.synchronize(device)
    except torch.cuda.OutOfMemoryError as error:
        torch.cuda.empty_cache()
        raise RuntimeError(
            "CUDA ran out of memory. Retry with --chunk-seconds 10; if needed, use 5."
        ) from error
    elapsed = time.monotonic() - started
    peak_allocated = torch.cuda.max_memory_allocated(device)
    peak_reserved = torch.cuda.max_memory_reserved(device)

    outputs: list[dict[str, Any]] = []
    for index, (stem, output_path) in enumerate(zip(stems, output_paths)):
        write_wav_atomic(output_path, separated[index], sample_rate, subtype)
        outputs.append(
            {
                "stem": stem,
                "path": str(output_path.resolve()),
                "sample_rate": sample_rate,
                "channels": 2,
                "frames": int(separated.shape[-1]),
                "subtype": subtype,
                "peak": float(np.max(np.abs(separated[index]))),
            }
        )
        print(f"Wrote: {output_path}")

    manifest = {
        "schema_version": 1,
        "input": {
            "path": str(input_path),
            "sha256": sha256_file(input_path),
            "duration_seconds": duration_seconds,
            "decoded_sample_rate": sample_rate,
            "decoded_channels": 2,
        },
        "model": {
            "name": "MVSep Mega 53 Stems",
            "release": MODEL_VERSION,
            "upstream_commit": MODEL_COMMIT,
            "config_path": str(config_path),
            "config_sha256_expected": CONFIG_SHA256,
            "checkpoint_path": str(checkpoint_path),
            "checkpoint_sha256_expected": CHECKPOINT_SHA256,
            "asset_checksums_verified": checksums_verified,
            "selected_stems": stems,
            "head_pruning": True,
        },
        "inference": {
            "chunk_size_samples": chunk_size,
            "chunk_seconds": chunk_size / sample_rate,
            "overlap": overlap,
            "precision": precision,
            "elapsed_seconds": elapsed,
            "real_time_factor": elapsed / duration_seconds,
            "model_load_seconds": model_load_seconds,
            "peak_cuda_allocated_bytes": peak_allocated,
            "peak_cuda_reserved_bytes": peak_reserved,
        },
        "environment": environment,
        "outputs": outputs,
    }
    write_json_atomic(manifest_path, manifest)
    print(
        f"Done in {elapsed:.2f}s (RTF {elapsed / duration_seconds:.3f}); "
        f"peak CUDA allocated {peak_allocated / 1024**3:.2f} GiB, "
        f"reserved {peak_reserved / 1024**3:.2f} GiB"
    )
    del separated, audio
    gc.collect()
    torch.cuda.empty_cache()
    return manifest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Separate acoustic-guitar and electric-guitar with the official "
            "MVSep Mega v1.0.21 checkpoint."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="Audio files or directories. Directories are scanned recursively.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("models/mvsep_mega"),
        help="Directory created by download_mvsep_mega.py",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("mvsep_output"),
        help="Output root (default: mvsep_output)",
    )
    parser.add_argument(
        "--stems",
        nargs="+",
        default=list(DEFAULT_STEMS),
        help="Stem names to retain (default: acoustic-guitar electric-guitar)",
    )
    parser.add_argument(
        "--device", default="cuda:0", help="CUDA device (default: cuda:0)"
    )
    parser.add_argument(
        "--chunk-seconds",
        type=float,
        default=None,
        help="Override the official 20-second chunk; use 10 or 5 only for OOM",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=None,
        help="Override official overlap count (default from config: 2)",
    )
    parser.add_argument(
        "--precision",
        choices=("fp16", "bf16", "fp32"),
        default="fp16",
        help="CUDA inference precision (default: fp16, matching official AMP behavior)",
    )
    parser.add_argument(
        "--subtype",
        choices=("FLOAT", "PCM_24", "PCM_16"),
        default="FLOAT",
        help="Output WAV subtype (default: FLOAT)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace existing song outputs"
    )
    parser.add_argument(
        "--skip-checksum",
        action="store_true",
        help="Check model file sizes but skip SHA-256 verification",
    )
    parser.add_argument(
        "--check-env",
        action="store_true",
        help="Print CUDA/MSST environment information and exit without loading weights",
    )
    args = parser.parse_args()
    if not args.check_env and not args.inputs:
        parser.error("at least one input is required unless --check-env is used")
    if args.chunk_seconds is not None and args.chunk_seconds <= 0:
        parser.error("--chunk-seconds must be positive")
    if args.overlap is not None and args.overlap < 2:
        parser.error("--overlap must be at least 2")
    return args


def main() -> int:
    args = parse_args()
    try:
        load_runtime_dependencies()
        device = parse_device(args.device)
        environment = runtime_info(device)
        print_environment(environment)
        if args.precision == "bf16" and not torch.cuda.is_bf16_supported():
            raise RuntimeError(f"{environment['gpu']} does not report BF16 support.")
        if args.check_env:
            print("CUDA/MSST environment check passed.")
            return 0

        model_dir = args.model_dir.expanduser().resolve()
        config_path = model_dir / CONFIG_FILENAME
        checkpoint_path = model_dir / CHECKPOINT_FILENAME
        verify_asset(
            config_path,
            expected_size=CONFIG_SIZE,
            expected_sha256=CONFIG_SHA256,
            skip_checksum=args.skip_checksum,
        )
        verify_asset(
            checkpoint_path,
            expected_size=CHECKPOINT_SIZE,
            expected_sha256=CHECKPOINT_SHA256,
            skip_checksum=args.skip_checksum,
        )
        config = load_config(config_path)
        selected_indices, sample_rate = validate_config(config, args.stems)
        chunk_size = config["inference"]["chunk_size"]
        if args.chunk_seconds is not None:
            chunk_size = round(args.chunk_seconds * sample_rate)
        overlap = args.overlap or config["inference"]["num_overlap"]

        # Favor fast CUDA kernels on the RTX 5090; autocast controls inference precision.
        torch.backends.cudnn.benchmark = True
        if hasattr(torch.backends.cuda.matmul, "allow_tf32"):
            torch.backends.cuda.matmul.allow_tf32 = True
        model, model_load_seconds = load_model(
            config,
            checkpoint_path,
            selected_indices,
            device,
        )
        output_root = args.output_dir.expanduser().resolve()
        inputs = collect_inputs(args.inputs, exclude_root=output_root)
        destinations: dict[Path, Path] = {}
        for input_path in inputs:
            destination = output_folder_for(input_path, output_root)
            if destination in destinations:
                raise ValueError(
                    "Two inputs would write to the same output directory: "
                    f"{destinations[destination]} and {input_path}. "
                    "Rename one input or run them with different --output-dir values."
                )
            destinations[destination] = input_path
        manifests = []
        for input_path in inputs:
            manifests.append(
                process_file(
                    input_path,
                    model=model,
                    output_root=output_root,
                    stems=args.stems,
                    sample_rate=sample_rate,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    precision=args.precision,
                    subtype=args.subtype,
                    overwrite=args.overwrite,
                    device=device,
                    environment=environment,
                    config_path=config_path,
                    checkpoint_path=checkpoint_path,
                    checksums_verified=not args.skip_checksum,
                    model_load_seconds=model_load_seconds,
                )
            )
        print("\nCreated manifests:")
        for manifest in manifests:
            print(f"  {manifest}")
        return 0
    except (
        FileNotFoundError,
        FileExistsError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
