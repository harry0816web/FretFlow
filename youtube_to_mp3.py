#!/usr/bin/env python3
"""Download one YouTube video and convert its audio to MP3."""

from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def normalize_url(value: str) -> str:
    """Remove shell escapes that may have been pasted inside quotes."""
    return re.sub(r"\\([?=&])", r"\1", value.strip())


def is_youtube_url(value: str) -> bool:
    """Accept individual video URLs, excluding channels and playlists."""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        return False
    if host == "youtu.be":
        video_id = parsed.path.strip("/")
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            match = re.fullmatch(r"/(?:shorts|live|embed)/([^/]+)/?", parsed.path)
            video_id = match.group(1) if match else ""
    else:
        return False
    return re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) is not None


def download_mp3(url: str, output_dir: Path) -> None:
    url = normalize_url(url)
    if not is_youtube_url(url):
        raise ValueError("請輸入單支 YouTube 影片網址，不能使用首頁、頻道或播放清單網址。")

    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "找不到 FFmpeg。請先安裝 FFmpeg，並確認它已加入 PATH。"
        )

    if importlib.util.find_spec("yt_dlp") is None:
        raise RuntimeError(
            "找不到 yt-dlp。請先執行：python -m pip install -U yt-dlp"
        )

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(title)s.%(ext)s")
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-playlist",
        "--no-simulate",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--output",
        output_template,
    ]

    print("開始下載並轉換成 MP3…", flush=True)
    # A zero exit code can also mean an empty playlist. Verify the actual
    # post-processed output from this invocation, not any existing MP3.
    with tempfile.TemporaryDirectory(prefix="youtube-mp3-") as temp_dir:
        report = Path(temp_dir) / "output-paths.txt"
        command.extend(["--print-to-file", "after_move:filepath", str(report), url])
        subprocess.run(command, check=True)
        paths = report.read_text(encoding="utf-8").splitlines() if report.exists() else []
        if len(paths) != 1:
            raise RuntimeError("未取得單支影片的 MP3 輸出，下載未完成。")
        output_file = Path(paths[0])
        if (output_file.suffix.lower() != ".mp3"
                or not output_file.is_file() or output_file.stat().st_size == 0):
            raise RuntimeError("轉換後的 MP3 不存在或是空檔案，下載未完成。")
    print(f"完成！檔案已存到：{output_file}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="將單支 YouTube 影片下載並轉換成 MP3。"
    )
    parser.add_argument("url", nargs="?", help="YouTube 影片網址")
    parser.add_argument(
        "-o",
        "--output-dir",
        default="downloads",
        help="輸出資料夾（預設：downloads）",
    )
    args = parser.parse_args()

    url = args.url or input("請貼上 YouTube 網址：").strip()
    try:
        download_mp3(url, Path(args.output_dir))
    except subprocess.CalledProcessError as error:
        print(f"下載失敗（程式碼 {error.returncode}）。請確認網址仍可觀看。", file=sys.stderr)
        return error.returncode or 1
    except (RuntimeError, ValueError) as error:
        print(f"錯誤：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
