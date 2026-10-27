#!/usr/bin/env python3
"""Download and verify the official MVSep Mega v1.0.21 model assets.

This script only uses the Python standard library so it can be copied to a
workstation and run before the inference environment is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


RELEASE_BASE_URL = (
    "https://github.com/ZFTurbo/Music-Source-Separation-Training/"
    "releases/download/v1.0.21"
)
BUFFER_SIZE = 8 * 1024 * 1024
MIN_FREE_SPACE = 256 * 1024 * 1024


@dataclass(frozen=True)
class Asset:
    kind: str
    filename: str
    size: int
    sha256: str

    @property
    def url(self) -> str:
        return f"{RELEASE_BASE_URL}/{self.filename}"


ASSETS = (
    Asset(
        kind="config",
        filename="mvsep_mega_model_bs_roformer_53_stems.yaml",
        size=4_184,
        sha256="7e198062a251587088adb91215a4f44ab59e67bd62fcc805cf54d6e7dfc51103",
    ),
    Asset(
        kind="checkpoint",
        filename="mvsep_mega_model_bs_roformer_53_stems_v1.ckpt",
        size=1_368_919_887,
        sha256="c62820893bbf86d4e734f966bd142d9157cfc8bb8e79e9d8f9ea553f3ff3519f",
    ),
)


def human_size(size: float) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(BUFFER_SIZE):
            digest.update(block)
    return digest.hexdigest()


def verify_asset(path: Path, asset: Asset, *, quiet: bool = False) -> bool:
    if not path.is_file():
        return False
    actual_size = path.stat().st_size
    if actual_size != asset.size:
        if not quiet:
            print(
                f"Size mismatch for {path.name}: expected {asset.size}, "
                f"got {actual_size}",
                file=sys.stderr,
            )
        return False
    if not quiet:
        print(f"Verifying SHA-256 for {path.name} ...")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != asset.sha256:
        if not quiet:
            print(
                f"SHA-256 mismatch for {path.name}:\n"
                f"  expected: {asset.sha256}\n"
                f"  actual:   {actual_sha256}",
                file=sys.stderr,
            )
        return False
    return True


def ensure_disk_space(output_dir: Path, required: int) -> None:
    free = shutil.disk_usage(output_dir).free
    if free < required + MIN_FREE_SPACE:
        raise RuntimeError(
            f"Not enough free disk space in {output_dir}: need at least "
            f"{human_size(required + MIN_FREE_SPACE)}, have {human_size(free)}"
        )


def download_asset(
    asset: Asset,
    output_dir: Path,
    *,
    force: bool,
    resume: bool,
    retries: int,
) -> Path:
    destination = output_dir / asset.filename
    partial = output_dir / f"{asset.filename}.part"

    if destination.exists():
        if verify_asset(destination, asset):
            print(f"Already complete: {destination}")
            return destination
        if not force:
            raise RuntimeError(
                f"Existing file failed verification: {destination}. "
                "Move it aside or rerun with --force."
            )
        destination.unlink()

    if not resume and partial.exists():
        partial.unlink()
    if partial.exists() and partial.stat().st_size > asset.size:
        print(f"Discarding oversized partial file: {partial}")
        partial.unlink()

    current_size = partial.stat().st_size if partial.exists() else 0
    ensure_disk_space(output_dir, asset.size - current_size)

    for attempt in range(1, retries + 1):
        current_size = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "guitar-hero-mvsep-downloader/1.0"}
        if resume and current_size:
            headers["Range"] = f"bytes={current_size}-"

        request = urllib.request.Request(asset.url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                status = getattr(response, "status", 200)
                if current_size and status == 206:
                    mode = "ab"
                    downloaded = current_size
                    print(
                        f"Resuming {asset.filename} at {human_size(current_size)} "
                        f"of {human_size(asset.size)}"
                    )
                else:
                    if current_size:
                        print("Server did not accept the range request; restarting download.")
                    mode = "wb"
                    downloaded = 0
                    current_size = 0
                    print(f"Downloading {asset.filename} ({human_size(asset.size)})")

                started = time.monotonic()
                last_report = started
                with partial.open(mode) as handle:
                    while True:
                        block = response.read(BUFFER_SIZE)
                        if not block:
                            break
                        handle.write(block)
                        downloaded += len(block)
                        now = time.monotonic()
                        if now - last_report >= 1.0:
                            elapsed = max(now - started, 1e-6)
                            speed = (downloaded - current_size) / elapsed
                            percent = min(downloaded / asset.size * 100, 100.0)
                            print(
                                f"\r  {percent:6.2f}%  {human_size(downloaded)} / "
                                f"{human_size(asset.size)}  {human_size(speed)}/s",
                                end="",
                                flush=True,
                            )
                            last_report = now
                    handle.flush()
                    os.fsync(handle.fileno())
                print()

            if partial.stat().st_size != asset.size:
                raise RuntimeError(
                    f"Incomplete download: expected {asset.size} bytes, "
                    f"got {partial.stat().st_size}"
                )
            if not verify_asset(partial, asset):
                # A complete file with the wrong digest cannot be resumed.
                # Remove only the downloader-owned temporary file so the retry
                # starts cleanly from byte zero.
                partial.unlink()
                raise RuntimeError(f"Checksum verification failed for {partial}")

            partial.replace(destination)
            print(f"Saved: {destination}")
            return destination
        except (OSError, RuntimeError, urllib.error.URLError) as exc:
            if attempt == retries:
                raise RuntimeError(
                    f"Failed to download {asset.filename} after {retries} attempts: {exc}"
                ) from exc
            wait_seconds = min(2 ** (attempt - 1), 10)
            print(
                f"Download attempt {attempt}/{retries} failed: {exc}\n"
                f"Retrying in {wait_seconds} seconds ...",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)

    raise AssertionError("unreachable")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download and verify the official MVSep Mega 53-stem v1.0.21 "
            "checkpoint and configuration."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("models/mvsep_mega"),
        help="Destination directory (default: models/mvsep_mega)",
    )
    parser.add_argument(
        "--asset",
        choices=("all", "config", "checkpoint"),
        default="all",
        help="Download both files or only one asset (default: all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing final file only if it fails verification",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Discard any .part file and restart from byte zero",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Maximum download attempts per asset (default: 3)",
    )
    args = parser.parse_args()
    if args.retries < 1:
        parser.error("--retries must be at least 1")
    return args


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    selected = [asset for asset in ASSETS if args.asset in ("all", asset.kind)]
    try:
        for asset in selected:
            download_asset(
                asset,
                output_dir,
                force=args.force,
                resume=not args.no_resume,
                retries=args.retries,
            )
    except KeyboardInterrupt:
        print("\nInterrupted. The .part file was kept for the next run.", file=sys.stderr)
        return 130
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("MVSep Mega assets are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
