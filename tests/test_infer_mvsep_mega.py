import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import infer_mvsep_mega as inference


class MVSepMegaInferenceHelpersTests(unittest.TestCase):
    def test_validate_config_selects_official_guitar_indices(self):
        instruments = [f"stem-{index}" for index in range(53)]
        instruments[1] = "acoustic-guitar"
        instruments[16] = "electric-guitar"
        config = {
            "audio": {"sample_rate": 44_100, "num_channels": 2},
            "model": {"num_stems": 53},
            "training": {"instruments": instruments},
            "inference": {},
        }

        indices, sample_rate = inference.validate_config(
            config,
            ["acoustic-guitar", "electric-guitar"],
        )

        self.assertEqual(indices, [1, 16])
        self.assertEqual(sample_rate, 44_100)

    def test_collect_inputs_recurses_and_ignores_non_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "album"
            nested.mkdir()
            first = root / "a.mp3"
            second = nested / "b.wav"
            first.touch()
            second.touch()
            (nested / "notes.txt").touch()

            found = inference.collect_inputs([str(root)])

            self.assertEqual(found, [first.resolve(), second.resolve()])

    def test_verify_asset_checks_size_and_digest(self):
        payload = b"mvsep-test"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "asset.bin"
            path.write_bytes(payload)

            inference.verify_asset(
                path,
                expected_size=len(payload),
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                skip_checksum=False,
            )

    def test_query_nvidia_smi_combines_driver_and_process_memory(self):
        responses = iter(
            [
                subprocess.CompletedProcess(
                    [],
                    0,
                    stdout="GPU-test, 2048, 32768, 97, 412.5\n",
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    [],
                    0,
                    stdout="GPU-test, 1234, 1800\nGPU-other, 1234, 900\n",
                    stderr="",
                ),
            ]
        )

        with patch.object(
            inference.subprocess,
            "run",
            side_effect=lambda *args, **kwargs: next(responses),
        ):
            sample = inference.query_nvidia_smi(0, 1234)

        self.assertEqual(sample["process_used_bytes"], 1800 * 1024**2)
        self.assertEqual(sample["device_used_bytes"], 2048 * 1024**2)
        self.assertEqual(sample["device_total_bytes"], 32768 * 1024**2)
        self.assertEqual(sample["gpu_utilization_percent"], 97.0)
        self.assertEqual(sample["power_draw_watts"], 412.5)

    def test_summarize_gpu_samples_reports_peaks_and_averages(self):
        summary = inference.summarize_gpu_samples(
            [
                {
                    "process_used_bytes": 100,
                    "device_used_bytes": 200,
                    "device_total_bytes": 1000,
                    "gpu_utilization_percent": 50,
                    "power_draw_watts": 300,
                },
                {
                    "process_used_bytes": 150,
                    "device_used_bytes": 250,
                    "device_total_bytes": 1000,
                    "gpu_utilization_percent": 90,
                    "power_draw_watts": 400,
                },
            ]
        )

        self.assertEqual(summary["process_peak_used_bytes"], 150)
        self.assertEqual(summary["device_peak_used_bytes"], 250)
        self.assertEqual(summary["gpu_peak_utilization_percent"], 90)
        self.assertEqual(summary["gpu_average_utilization_percent"], 70)
        self.assertEqual(summary["power_average_watts"], 350)

    def test_monitor_degrades_when_nvidia_smi_is_unavailable(self):
        monitor = inference.NvidiaSmiMonitor(0)
        with patch.object(
            inference,
            "query_nvidia_smi",
            side_effect=FileNotFoundError("nvidia-smi missing"),
        ):
            monitor.start()

        summary = monitor.session_summary()
        self.assertEqual(summary["backend"], "unavailable")
        self.assertIn("nvidia-smi missing", summary["error"])


if __name__ == "__main__":
    unittest.main()
