#!/usr/bin/env python3
"""Validate workstation MVSep and guitar TAB smoke-test artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PRODUCT_STEMS = (
    "acoustic-guitar",
    "electric-guitar",
    "bass",
    "drums",
    "vocal",
)
GUITAR_STEMS = ("acoustic-guitar", "electric-guitar")


class ValidationError(ValueError):
    """Raised when a smoke-test artifact does not meet the contract."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"Cannot read JSON from {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValidationError(f"Expected a JSON object in {path}")
    return payload


def require_number(payload: dict[str, Any], key: str, *, positive: bool = False) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError(f"{key} must be numeric")
    result = float(value)
    if positive and result <= 0:
        raise ValidationError(f"{key} must be greater than zero")
    return result


def validate_separation_manifest(
    payload: dict[str, Any],
    *,
    expected_stems: tuple[str, ...] = PRODUCT_STEMS,
    minimum_duration: float = 30.0,
) -> dict[str, Any]:
    if payload.get("schema_version") != 1:
        raise ValidationError("Separation manifest schema_version must be 1")

    selected = payload.get("model", {}).get("selected_stems")
    if not isinstance(selected, list) or set(selected) != set(expected_stems):
        raise ValidationError(
            f"Expected stems {list(expected_stems)}, found {selected!r}"
        )
    outputs = payload.get("outputs")
    if not isinstance(outputs, list):
        raise ValidationError("Separation manifest outputs must be a list")
    output_stems = [output.get("stem") for output in outputs if isinstance(output, dict)]
    if set(output_stems) != set(expected_stems) or len(output_stems) != len(expected_stems):
        raise ValidationError("Separation outputs do not match selected stems")

    duration = require_number(payload.get("input", {}), "duration_seconds", positive=True)
    if duration < minimum_duration:
        raise ValidationError(
            f"Input duration {duration:.2f}s is below the {minimum_duration:.2f}s requirement"
        )
    inference = payload.get("inference", {})
    elapsed = require_number(inference, "elapsed_seconds", positive=True)
    rtf = require_number(inference, "real_time_factor", positive=True)
    allocated = require_number(inference, "peak_cuda_allocated_bytes", positive=True)
    reserved = require_number(inference, "peak_cuda_reserved_bytes", positive=True)
    environment = payload.get("environment", {})
    for key in ("gpu", "torch", "torch_cuda", "python"):
        if not environment.get(key):
            raise ValidationError(f"environment.{key} is required")

    return {
        "duration_seconds": duration,
        "elapsed_seconds": elapsed,
        "real_time_factor": rtf,
        "model_load_seconds": require_number(inference, "model_load_seconds", positive=True),
        "peak_cuda_allocated_gib": round(allocated / 1024**3, 3),
        "peak_cuda_reserved_gib": round(reserved / 1024**3, 3),
        "gpu": environment["gpu"],
        "python": environment["python"],
        "torch": environment["torch"],
        "cuda": environment["torch_cuda"],
        "stems": selected,
    }


def validate_tab_payload(payload: dict[str, Any], stem: str) -> dict[str, Any]:
    if stem not in GUITAR_STEMS:
        raise ValidationError(f"TAB validation is not supported for {stem}")
    if payload.get("format") != "basic-pitch-tab-v1":
        raise ValidationError(f"Unexpected TAB format for {stem}")
    source = payload.get("input", {}).get("path")
    if not isinstance(source, str) or stem not in Path(source).stem:
        raise ValidationError(f"TAB input for {stem} does not identify that stem")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise ValidationError(f"TAB for {stem} has no events")
    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        raise ValidationError(f"TAB diagnostics are missing for {stem}")
    elapsed = require_number(payload.get("transcription", {}), "elapsed_seconds", positive=True)
    return {
        "stem": stem,
        "event_count": len(events),
        "elapsed_seconds": elapsed,
        "dropped_note_assignments": int(diagnostics.get("dropped_note_assignments", 0)),
        "unresolved_onset_groups": int(diagnostics.get("unresolved_onset_groups", 0)),
    }


def parse_tab_argument(value: str) -> tuple[str, Path]:
    stem, separator, raw_path = value.partition("=")
    if not separator or stem not in GUITAR_STEMS or not raw_path:
        raise argparse.ArgumentTypeError(
            "TAB must be acoustic-guitar=PATH or electric-guitar=PATH"
        )
    return stem, Path(raw_path).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate FretFlow GPU separation and TAB smoke-test artifacts."
    )
    parser.add_argument("manifest", type=Path, help="MVSep separation manifest.json")
    parser.add_argument(
        "--tab",
        action="append",
        default=[],
        type=parse_tab_argument,
        metavar="STEM=PATH",
        help="Guitar TAB JSON; repeat for acoustic-guitar and electric-guitar",
    )
    parser.add_argument(
        "--expected-stems",
        nargs="+",
        default=list(PRODUCT_STEMS),
        help="Expected separation stems (default: the five product stems)",
    )
    parser.add_argument("--minimum-duration", type=float, default=30.0)
    parser.add_argument("--require-tabs", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    separation = validate_separation_manifest(
        read_json(args.manifest.expanduser()),
        expected_stems=tuple(args.expected_stems),
        minimum_duration=args.minimum_duration,
    )
    tabs = {stem: validate_tab_payload(read_json(path), stem) for stem, path in args.tab}
    if args.require_tabs and set(tabs) != set(GUITAR_STEMS):
        raise ValidationError(
            "--require-tabs needs both acoustic-guitar and electric-guitar TAB files"
        )
    print(json.dumps({"separation": separation, "tabs": tabs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
