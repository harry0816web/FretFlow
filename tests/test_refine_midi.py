import unittest
import contextlib
import io
import tempfile
from pathlib import Path

import numpy as np
import pretty_midi

from basic_pitch_tab import (Fingering, MidiNote, TabCandidate, TabEvent, TUNINGS,
                             optimize_sustained_fingerings)
from refine_midi import Evidence, Settings, clean_notes, enforce_string_durations, main, make_midi


def note(pitch=64, start=0, end=0.5, amplitude=0.8):
    return MidiNote(pitch, start, end, amplitude)


class RefinementTests(unittest.TestCase):
    def clean(self, notes, evidence=None):
        return clean_notes(notes, Settings(), TUNINGS["standard"], 22, 0, evidence)

    def evidence(self):
        times = np.arange(0, 2, 0.01)
        return Evidence(times, np.full((len(times), 88), 0.6), np.zeros((len(times), 88)))

    def test_filter_requires_both_weak_and_short(self):
        weak_short = note(end=0.1, amplitude=0.3)
        strong_short = note(pitch=65, end=0.1, amplitude=0.8)
        weak_long = note(pitch=67, end=0.8, amplitude=0.3)
        kept, report = self.clean([weak_short, strong_short, weak_long])
        self.assertEqual(kept, [strong_short, weak_long])
        self.assertEqual(report["changes"][0]["reason"], "weak_and_short")

    def test_no_evidence_does_not_merge_repeated_plucks(self):
        notes = [note(end=0.5), note(start=0.52, end=1)]
        kept, report = self.clean(notes)
        self.assertEqual(len(kept), 2)
        self.assertEqual(report["join_candidates"], 1)

    def test_sustained_evidence_without_attack_can_join(self):
        kept, report = self.clean([note(end=0.5), note(start=0.52, end=1)], self.evidence())
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0].start, kept[0].end), (0, 1))
        self.assertEqual(report["changes"][0]["action"], "join")

    def test_attack_protects_repeated_pluck_including_zero_gap(self):
        for gap in (0, 0.02):
            evidence = self.evidence()
            evidence.onsets[50:55, 64 - 21] = 0.8
            kept, _ = self.clean([note(end=0.5), note(start=0.5 + gap, end=1)], evidence)
            self.assertEqual(len(kept), 2)

    def test_activation_rise_protects_attack_with_weak_onset(self):
        evidence = self.evidence()
        evidence.frames[52:, 64 - 21] = 0.9
        kept, _ = self.clean([note(end=0.5), note(start=0.52, end=1)], evidence)
        self.assertEqual(len(kept), 2)

    def test_silent_gap_and_long_gap_are_not_bridged(self):
        evidence = self.evidence()
        evidence.frames[49:54, 64 - 21] = 0
        kept, _ = self.clean([note(end=0.5), note(start=0.52, end=1)], evidence)
        self.assertEqual(len(kept), 2)
        kept, _ = self.clean([note(end=0.5), note(start=0.7, end=1)], self.evidence())
        self.assertEqual(len(kept), 2)

    def test_fretboard_range_uses_tuning_and_capo(self):
        kept, report = clean_notes([note(pitch=40)], Settings(), TUNINGS["standard"], 22, 2)
        self.assertEqual(kept, [])
        self.assertEqual(report["changes"][0]["reason"], "outside_selected_fretboard")

    def test_evidence_rejects_nan_and_bad_shapes(self):
        with self.assertRaises(ValueError):
            Evidence(np.array([0, float("nan")]), np.zeros((2, 88)), np.zeros((2, 88)))
        with self.assertRaises(ValueError):
            Evidence(np.arange(2), np.zeros((2, 87)), np.zeros((2, 88)))

    def test_string_duration_correction_remembers_nonadjacent_events(self):
        def event(string, pitch, start, end):
            return {"notes": [{"string": string, "midi_pitch": pitch,
                               "start_seconds": start, "end_seconds": end}]}
        events = [event(1, 40, 0, 3), event(2, 45, 1, 1.5), event(1, 42, 2, 4)]
        changes = enforce_string_durations(events)
        self.assertEqual(len(changes), 1)
        self.assertEqual(events[0]["offset_seconds"], 2)
        self.assertEqual(events[1]["offset_seconds"], 1.5)

    def test_search_preserves_held_note_by_choosing_another_string(self):
        def candidate(n, string, fret, cost=0):
            return TabCandidate((Fingering(string, fret, n),), (), cost, float(fret))
        first = note(64, 0, 3)
        middle = note(59, 1, 1.5)
        last = note(65, 2, 4)
        events = [TabEvent(0, (first,), (candidate(first, 6, 0),)),
                  TabEvent(1, (middle,), (candidate(middle, 5, 0),)),
                  TabEvent(2, (last,), (candidate(last, 6, 1), candidate(last, 4, 10, 1)))]
        path = optimize_sustained_fingerings(events)
        self.assertEqual(path[-1].fingerings[0].string, 4)

    def test_cli_preserves_source_and_refuses_overwriting_results(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.mid"
            output = Path(directory) / "refined"
            make_midi([note(64, 0.1, 0.6), note(67, 0.12, 0.7),
                       note(60, 1, 1.1, 0.3)], "fixture").write(str(source))
            original = source.read_bytes()
            args = [str(source), "--output-dir", str(output)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
            self.assertEqual(source.read_bytes(), original)
            result = pretty_midi.PrettyMIDI(str(output / "input.playable.mid"))
            notes = sorted(result.instruments[0].notes, key=lambda n: n.start)
            self.assertEqual(len(notes), 2)
            # Strum offsets must not be snapped to the first onset in a group.
            self.assertAlmostEqual(notes[1].start - notes[0].start, 0.02, delta=0.003)
            saved = (output / "input.playable.mid").read_bytes()
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main(args)
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual((output / "input.playable.mid").read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
