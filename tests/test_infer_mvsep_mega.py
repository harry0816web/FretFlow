import hashlib
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
