import unittest

from basic_pitch_tab import (
    TUNINGS,
    MidiNote,
    TabEvent,
    build_candidates,
    create_tab_events,
    group_note_events,
    optimize_fingerings,
    positions_for_pitch,
)


def note(pitch, start=0.0, end=0.4, amplitude=0.8):
    return MidiNote(pitch, start, end, amplitude)


class MidiGroupingTests(unittest.TestCase):
    def test_groups_near_simultaneous_notes_and_deduplicates_pitch(self):
        groups = group_note_events(
            [note(64, 0.0, amplitude=0.5), note(64, 0.02, amplitude=0.9), note(67, 0.03)],
            0.05,
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual([item.pitch for item in groups[0][1]], [64, 67])
        self.assertEqual(groups[0][1][0].amplitude, 0.9)


class FretboardTests(unittest.TestCase):
    def test_positions_for_middle_c_include_multiple_strings(self):
        self.assertEqual(
            positions_for_pitch(60, TUNINGS["standard"], 22, 0),
            ((1, 20), (2, 15), (3, 10), (4, 5), (5, 1)),
        )

    def test_capo_rejects_notes_below_open_capo_pitch(self):
        self.assertEqual(positions_for_pitch(40, TUNINGS["standard"], 22, 2), ())

    def test_chord_candidates_use_distinct_strings_and_respect_stretch(self):
        candidates = build_candidates(
            [note(48), note(52), note(55)],
            TUNINGS["standard"],
            max_fret=22,
            capo=0,
            max_stretch=4,
            candidate_limit=64,
        )

        self.assertTrue(candidates)
        for candidate in candidates:
            strings = [item.string for item in candidate.fingerings]
            frets = [item.fret for item in candidate.fingerings if item.fret]
            self.assertEqual(len(strings), len(set(strings)))
            if frets:
                self.assertLessEqual(max(frets) - min(frets), 4)

    def test_global_optimizer_prefers_small_position_movement(self):
        first = build_candidates(
            [note(64, 0.0)], TUNINGS["standard"], 22, 0, 4, 64
        )
        second = build_candidates(
            [note(65, 0.1)], TUNINGS["standard"], 22, 0, 4, 64
        )
        path = optimize_fingerings(
            [TabEvent(0.0, (note(64),), first), TabEvent(0.1, (note(65),), second)]
        )

        self.assertLessEqual(abs(path[1].hand_position - path[0].hand_position), 2)


class OutputTests(unittest.TestCase):
    def test_basic_pitch_tuple_conversion_preserves_offsets(self):
        events, diagnostics = create_tab_events(
            [(0.1, 0.55, 64, 0.9, None), (0.11, 0.5, 67, 0.8, [0, 1])],
            TUNINGS["standard"],
            max_fret=22,
            capo=0,
            onset_tolerance=0.05,
            max_stretch=4,
            candidate_limit=64,
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["offset_seconds"], 0.55)
        self.assertEqual(len(events[0]["notes"]), 2)
        self.assertEqual(diagnostics["source_note_count"], 2)


if __name__ == "__main__":
    unittest.main()
