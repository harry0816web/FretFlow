import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_to_mp3 import download_mp3, is_youtube_url, normalize_url


class DownloadTests(unittest.TestCase):
    def test_quoted_shell_escapes(self):
        url = r" https://www.youtube.com/watch\?v\=uTUWCJjg1bc\&list\=example "
        self.assertEqual(normalize_url(url),
                         "https://www.youtube.com/watch?v=uTUWCJjg1bc&list=example")
        self.assertTrue(is_youtube_url(normalize_url(url)))

    def test_accepts_video_urls(self):
        for url in ["https://www.youtube.com/watch?v=uTUWCJjg1bc",
                    "https://youtu.be/uTUWCJjg1bc?t=20",
                    "https://m.youtube.com/shorts/uTUWCJjg1bc",
                    "https://youtube.com/live/uTUWCJjg1bc"]:
            with self.subTest(url=url):
                self.assertTrue(is_youtube_url(url))

    def test_rejects_non_video_urls(self):
        for url in ["https://www.youtube.com/",
                    "https://youtube.com/feed/recommended",
                    "https://youtube.com/playlist?list=example",
                    "https://youtube.com/@channel",
                    "https://youtube.com/watch?v=invalid",
                    "https://youtube.com.example.com/watch?v=uTUWCJjg1bc"]:
            with self.subTest(url=url):
                self.assertFalse(is_youtube_url(url))

    def run_fake_download(self, outcome):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            # An unrelated existing file must not turn an empty run into success.
            (output_dir / "old.mp3").write_bytes(b"existing file")
            def fake_run(command, check):
                self.assertEqual(command[-1], "https://www.youtube.com/watch?v=uTUWCJjg1bc")
                report = Path(command[command.index("--print-to-file") + 2])
                if outcome == "error":
                    raise subprocess.CalledProcessError(1, command)
                if outcome != "no_output":
                    result = output_dir / "Prophecy.mp3"
                    result.write_bytes(b"audio fixture" if outcome == "success" else b"")
                    report.write_text(str(result) + "\n", encoding="utf-8")
            stdout = io.StringIO()
            with patch("youtube_to_mp3.shutil.which", return_value="ffmpeg"), \
                    patch("youtube_to_mp3.importlib.util.find_spec", return_value=object()), \
                    patch("youtube_to_mp3.subprocess.run", side_effect=fake_run), \
                    contextlib.redirect_stdout(stdout):
                try:
                    download_mp3(r"https://www.youtube.com/watch\?v\=uTUWCJjg1bc", output_dir)
                except Exception:
                    self.assertNotIn("完成！", stdout.getvalue())
                    raise
            return stdout.getvalue()

    def test_empty_success_exit_is_failure(self):
        with self.assertRaisesRegex(RuntimeError, "未取得"):
            self.run_fake_download("no_output")

    def test_empty_file_is_failure(self):
        with self.assertRaisesRegex(RuntimeError, "空檔案"):
            self.run_fake_download("empty")

    def test_subprocess_failure_propagates(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_fake_download("error")

    def test_verified_output_reports_filename(self):
        self.assertIn("Prophecy.mp3", self.run_fake_download("success"))


if __name__ == "__main__":
    unittest.main()
