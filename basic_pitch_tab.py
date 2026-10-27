#!/usr/bin/env python3
"""Transcribe a guitar stem with Basic Pitch and optimize it into playable TAB.

The audio model is intentionally separated from the guitar-specific step:
Basic Pitch estimates timed MIDI notes, then a constrained Viterbi search assigns
each pitch to a string/fret while minimizing chord stretch and hand movement.
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
import time
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

TUNINGS: dict[str, tuple[int, ...]] = {
    "standard": (40, 45, 50, 55, 59, 64),
    "drop-d": (38, 45, 50, 55, 59, 64),
    "eb-standard": (39, 44, 49, 54, 58, 63),
    "d-standard": (38, 43, 48, 53, 57, 62),
}
STRING_NAMES = ("E2", "A2", "D3", "G3", "B3", "E4")


class TabInferenceError(RuntimeError):
    """A user-facing transcription failure."""


@dataclass(frozen=True)
class MidiNote:
    pitch: int
    start: float
    end: float
    amplitude: float
    pitch_bends: tuple[int, ...] = ()


@dataclass(frozen=True)
class Fingering:
    string: int
    fret: int
    note: MidiNote


@dataclass(frozen=True)
class TabCandidate:
    fingerings: tuple[Fingering, ...]
    dropped: tuple[MidiNote, ...]
    local_cost: float
    hand_position: float


@dataclass(frozen=True)
class TabEvent:
    onset: float
    source_notes: tuple[MidiNote, ...]
    candidates: tuple[TabCandidate, ...]


def midi_to_hz(pitch: int) -> float:
    return 440.0 * (2.0 ** ((pitch - 69) / 12.0))


def group_note_events(
    notes: Iterable[MidiNote], onset_tolerance: float
) -> list[tuple[float, tuple[MidiNote, ...]]]:
    """Group near-simultaneous notes without letting clusters drift indefinitely."""
    ordered = sorted(notes, key=lambda note: (note.start, note.pitch, -note.amplitude))
    groups: list[list[MidiNote]] = []
    anchors: list[float] = []
    for note in ordered:
        if not groups or note.start - anchors[-1] > onset_tolerance:
            groups.append([note])
            anchors.append(note.start)
        else:
            groups[-1].append(note)

    result: list[tuple[float, tuple[MidiNote, ...]]] = []
    for anchor, group in zip(anchors, groups):
        # Basic Pitch can emit duplicate pitches at almost the same onset. A guitar
        # transcription should retain only the strongest instance of that pitch.
        by_pitch: dict[int, MidiNote] = {}
        for note in group:
            current = by_pitch.get(note.pitch)
            if current is None or (note.amplitude, note.end) > (
                current.amplitude,
                current.end,
            ):
                by_pitch[note.pitch] = note
        result.append((anchor, tuple(sorted(by_pitch.values(), key=lambda n: n.pitch))))
    return result


def positions_for_pitch(
    pitch: int,
    tuning: Sequence[int],
    max_fret: int,
    capo: int,
) -> tuple[tuple[int, int], ...]:
    return tuple(
        (index + 1, pitch - open_pitch)
        for index, open_pitch in enumerate(tuning)
        if capo <= pitch - open_pitch <= max_fret
    )


def _hand_position(fingerings: Sequence[Fingering], capo: int) -> float:
    fretted = [item.fret for item in fingerings if item.fret > capo]
    return float(min(fretted)) if fretted else float(capo)


def _local_cost(
    fingerings: Sequence[Fingering], dropped: Sequence[MidiNote], capo: int
) -> float:
    fretted = [item.fret for item in fingerings if item.fret > capo]
    stretch = max(fretted) - min(fretted) if len(fretted) > 1 else 0
    strings = sorted(item.string for item in fingerings)
    gaps = sum(
        max(0, right - left - 1) for left, right in itertools.pairwise(strings)
    )
    high_fret = sum(max(0, item.fret - 12) for item in fingerings)
    open_strings = sum(item.fret == capo for item in fingerings)
    dropped_cost = sum(18.0 + 8.0 * note.amplitude for note in dropped)
    return (
        stretch * 0.85
        + gaps * 0.18
        + high_fret * 0.08
        + sum(item.fret for item in fingerings) * 0.018
        - open_strings * 0.12
        + dropped_cost
    )


def _enumerate_subset_fingerings(
    retained: Sequence[MidiNote],
    tuning: Sequence[int],
    max_fret: int,
    capo: int,
    max_stretch: int,
    raw_limit: int = 12_000,
) -> list[tuple[Fingering, ...]]:
    choices: list[tuple[MidiNote, tuple[tuple[int, int], ...]]] = []
    for note in retained:
        positions = positions_for_pitch(note.pitch, tuning, max_fret, capo)
        if not positions:
            return []
        choices.append((note, positions))
    choices.sort(key=lambda item: (len(item[1]), -item[0].pitch))

    results: list[tuple[Fingering, ...]] = []

    def visit(
        index: int,
        used_strings: set[int],
        selected: list[Fingering],
        fretted: list[int],
    ) -> None:
        if len(results) >= raw_limit:
            return
        if index == len(choices):
            results.append(tuple(sorted(selected, key=lambda item: item.string)))
            return
        note, positions = choices[index]
        for string, fret in positions:
            if string in used_strings:
                continue
            next_fretted = fretted
            if fret > capo:
                next_fretted = [*fretted, fret]
                if max(next_fretted) - min(next_fretted) > max_stretch:
                    continue
            used_strings.add(string)
            selected.append(Fingering(string=string, fret=fret, note=note))
            visit(index + 1, used_strings, selected, next_fretted)
            selected.pop()
            used_strings.remove(string)

    visit(0, set(), [], [])
    return results


def build_candidates(
    notes: Sequence[MidiNote],
    tuning: Sequence[int],
    max_fret: int,
    capo: int,
    max_stretch: int,
    candidate_limit: int,
) -> tuple[TabCandidate, ...]:
    playable = [
        note
        for note in notes
        if positions_for_pitch(note.pitch, tuning, max_fret, capo)
    ]
    inherently_dropped = [note for note in notes if note not in playable]
    # False-positive polyphony is common in AMT output. Prefer the six strongest
    # distinct pitches, but account for every omitted source note in diagnostics.
    if len(playable) > len(tuning):
        ranked = sorted(playable, key=lambda note: (-note.amplitude, -note.pitch))
        inherently_dropped.extend(ranked[len(tuning) :])
        playable = sorted(ranked[: len(tuning)], key=lambda note: note.pitch)

    collected: list[TabCandidate] = []
    # Preserve as many pitches as possible. Only drop another pitch when no
    # physically valid assignment exists for the larger chord.
    for retained_count in range(len(playable), 0, -1):
        for retained in itertools.combinations(playable, retained_count):
            dropped = (
                *inherently_dropped,
                *(note for note in playable if note not in retained),
            )
            for fingerings in _enumerate_subset_fingerings(
                retained, tuning, max_fret, capo, max_stretch
            ):
                collected.append(
                    TabCandidate(
                        fingerings=fingerings,
                        dropped=dropped,
                        local_cost=_local_cost(fingerings, dropped, capo),
                        hand_position=_hand_position(fingerings, capo),
                    )
                )
        if collected:
            break

    collected.sort(
        key=lambda candidate: (
            candidate.local_cost,
            candidate.hand_position,
            tuple((item.string, item.fret) for item in candidate.fingerings),
        )
    )
    return tuple(collected[:candidate_limit])


def _transition_cost(
    previous: TabCandidate,
    current: TabCandidate,
    previous_onset: float,
    current_onset: float,
) -> float:
    delta = max(0.01, current_onset - previous_onset)
    urgency = 1.0 + max(0.0, 0.25 - delta) * 3.0
    movement = abs(current.hand_position - previous.hand_position) * 0.72 * urgency

    prev_by_string = {item.string: item for item in previous.fingerings}
    curr_by_string = {item.string: item for item in current.fingerings}
    conflict = 0.0
    continuity = 0.0
    for string in prev_by_string.keys() & curr_by_string.keys():
        before = prev_by_string[string]
        after = curr_by_string[string]
        if before.note.end > current_onset + 0.02 and before.note.pitch != after.note.pitch:
            conflict += 2.5
        if before.note.pitch == after.note.pitch:
            continuity -= 0.25

    prev_center = sum(item.string for item in previous.fingerings) / len(previous.fingerings)
    curr_center = sum(item.string for item in current.fingerings) / len(current.fingerings)
    vertical = abs(curr_center - prev_center) * 0.12
    return movement + conflict + continuity + vertical


def optimize_fingerings(events: Sequence[TabEvent]) -> list[TabCandidate]:
    """Find the minimum-cost fingering path across the whole performance."""
    if not events:
        return []
    costs = [candidate.local_cost for candidate in events[0].candidates]
    backpointers: list[list[int]] = []

    for event_index in range(1, len(events)):
        previous_event = events[event_index - 1]
        event = events[event_index]
        next_costs: list[float] = []
        pointers: list[int] = []
        for candidate in event.candidates:
            alternatives = [
                costs[previous_index]
                + _transition_cost(
                    previous_candidate,
                    candidate,
                    previous_event.onset,
                    event.onset,
                )
                for previous_index, previous_candidate in enumerate(
                    previous_event.candidates
                )
            ]
            best_previous = min(range(len(alternatives)), key=alternatives.__getitem__)
            next_costs.append(alternatives[best_previous] + candidate.local_cost)
            pointers.append(best_previous)
        costs = next_costs
        backpointers.append(pointers)

    selected_index = min(range(len(costs)), key=costs.__getitem__)
    path = [selected_index]
    for pointers in reversed(backpointers):
        selected_index = pointers[selected_index]
        path.append(selected_index)
    path.reverse()
    return [event.candidates[index] for event, index in zip(events, path)]


def optimize_sustained_fingerings(events: Sequence[TabEvent], beam_size: int = 64) -> list[TabCandidate]:
    """Approximate search that remembers held notes across nonadjacent events.

    The original Viterbi state only remembers the preceding onset group. Here
    every beam state also remembers all ringing strings. Reusing one has a
    duration/activation-weighted cost so the search first tries another position.
    This is a beam search, not an exact global optimum or a technique classifier.
    """
    if not events:
        return []
    states = [(0.0, (), {})]
    for index, event in enumerate(events):
        successors = {}
        for cost, path, active in states:
            for candidate_index, candidate in enumerate(event.candidates):
                held = {s: item for s, item in active.items() if item.note.end > event.onset}
                extra = candidate.local_cost
                if index:
                    extra += _transition_cost(path[-1], candidate, events[index - 1].onset, event.onset)
                for item in candidate.fingerings:
                    old = held.get(item.string)
                    if old and old.note.end > item.note.start + 0.02:
                        extra += 12.0 + 20.0 * (old.note.end - item.note.start) * old.note.amplitude
                    held[item.string] = item
                # A state is determined by the current fingering and all held
                # strings, not just the last chord. Keep its least-cost path.
                signature = (candidate_index, tuple(
                    (s, item.fret, item.note.start, item.note.end)
                    for s, item in sorted(held.items())
                ))
                next_cost = cost + extra
                if signature not in successors or next_cost < successors[signature][0]:
                    successors[signature] = (next_cost, (*path, candidate), held)
        states = sorted(successors.values(), key=lambda state: state[0])[:beam_size]
    return list(states[0][1])


def create_tab_events(
    note_events: Iterable[Sequence[Any]],
    tuning: Sequence[int],
    max_fret: int,
    capo: int,
    onset_tolerance: float,
    max_stretch: int,
    candidate_limit: int,
    sustain_aware: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    notes = [
        MidiNote(
            start=float(item[0]),
            end=float(item[1]),
            pitch=int(item[2]),
            amplitude=float(item[3]),
            pitch_bends=tuple(int(value) for value in (item[4] or ())),
        )
        for item in note_events
    ]
    grouped = group_note_events(notes, onset_tolerance)
    events: list[TabEvent] = []
    empty_groups = 0
    for onset, chord in grouped:
        candidates = build_candidates(
            chord,
            tuning,
            max_fret,
            capo,
            max_stretch,
            candidate_limit,
        )
        if not candidates:
            empty_groups += 1
            continue
        events.append(TabEvent(onset=onset, source_notes=chord, candidates=candidates))

    path = optimize_sustained_fingerings(events) if sustain_aware else optimize_fingerings(events)
    output: list[dict[str, Any]] = []
    dropped_notes = 0
    for event, candidate in zip(events, path):
        dropped_notes += len(candidate.dropped)
        output.append(
            {
                "onset_seconds": round(event.onset, 6),
                "offset_seconds": round(
                    max(item.note.end for item in candidate.fingerings), 6
                ),
                "score": round(
                    sum(item.note.amplitude for item in candidate.fingerings)
                    / len(candidate.fingerings),
                    6,
                ),
                "hand_position": round(candidate.hand_position, 3),
                "notes": [
                    {
                        "string": item.string,
                        "open_string": STRING_NAMES[item.string - 1],
                        "fret": item.fret,
                        "midi_pitch": item.note.pitch,
                        "start_seconds": round(item.note.start, 6),
                        "end_seconds": round(item.note.end, 6),
                        "amplitude": round(item.note.amplitude, 6),
                        "pitch_bends": list(item.note.pitch_bends),
                    }
                    for item in candidate.fingerings
                ],
                "dropped_midi_pitches": sorted(note.pitch for note in candidate.dropped),
            }
        )

    diagnostics = {
        "source_note_count": len(notes),
        "source_onset_groups": len(grouped),
        "output_event_count": len(output),
        "dropped_note_assignments": dropped_notes,
        "unresolved_onset_groups": empty_groups,
        "warnings": [],
    }
    if dropped_notes:
        diagnostics["warnings"].append(
            "Some simultaneous MIDI pitches were outside the fretboard or could not form a playable chord."
        )
    if empty_groups:
        diagnostics["warnings"].append(
            "Some onset groups contained no pitch playable in the selected tuning and fret range."
        )
    return output, diagnostics


def write_outputs(
    input_path: Path,
    output_path: Path,
    midi_path: Path,
    midi_data: Any,
    note_events: Sequence[Sequence[Any]],
    events: list[dict[str, Any]],
    diagnostics: dict[str, Any],
    args: argparse.Namespace,
    tuning: Sequence[int],
    model_path: Path,
    elapsed: float,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    midi_path.parent.mkdir(parents=True, exist_ok=True)
    midi_data.write(str(midi_path))
    duration = max((float(item[1]) for item in note_events), default=0.0)
    payload = {
        "format": "basic-pitch-tab-v1",
        "input": {
            "path": str(input_path.resolve()),
            "duration_seconds": round(duration, 6),
        },
        "midi_output": str(midi_path.resolve()),
        "model": {
            "name": "Spotify Basic Pitch",
            "version": version("basic-pitch"),
            "repository": "https://github.com/spotify/basic-pitch",
            "runtime_model": str(model_path),
        },
        "transcription": {
            "onset_threshold": args.onset_threshold,
            "frame_threshold": args.frame_threshold,
            "minimum_note_length_ms": args.minimum_note_length,
            "elapsed_seconds": round(elapsed, 3),
        },
        "tuning": {
            "name": args.tuning,
            "open_midi_low_to_high": list(tuning),
            "capo": args.capo,
            "max_fret": args.max_fret,
        },
        "optimization": {
            "algorithm": "global-viterbi-fretboard-v1",
            "onset_tolerance_seconds": args.onset_tolerance,
            "max_fret_span": args.max_stretch,
            "candidate_limit_per_event": args.candidate_limit,
            "objectives": [
                "preserve the maximum number of simultaneous pitches",
                "one pitch per string",
                "limit fretted chord span",
                "minimize hand-position movement over time",
                "penalize cutting sustained notes on a reused string",
            ],
        },
        "diagnostics": diagnostics,
        "events": events,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用 Spotify Basic Pitch 將吉他音檔轉成 MIDI，再全曲最佳化為可彈 TAB。"
    )
    parser.add_argument("input", type=Path, help="已分軌的吉他 MP3、WAV、FLAC 或 M4A")
    parser.add_argument("-o", "--output", type=Path, help="輸出 TAB JSON 路徑")
    parser.add_argument("--midi-output", type=Path, help="輸出 Basic Pitch MIDI 路徑")
    parser.add_argument("--save-model-output", type=Path, help="另存含時間軸的模型 NPZ，供保守斷點修復使用")
    parser.add_argument("--tuning", choices=tuple(TUNINGS), default="standard")
    parser.add_argument("--capo", type=int, default=0, help="實際錄音使用的 capo 格數")
    parser.add_argument("--max-fret", type=int, default=22)
    parser.add_argument("--max-stretch", type=int, default=4, help="和弦按弦最大 fret span")
    parser.add_argument("--onset-tolerance", type=float, default=0.05)
    parser.add_argument("--candidate-limit", type=int, default=64)
    parser.add_argument("--onset-threshold", type=float, default=0.5)
    parser.add_argument("--frame-threshold", type=float, default=0.3)
    parser.add_argument("--minimum-note-length", type=float, default=80.0, metavar="MS")
    return parser


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if not args.input.expanduser().is_file():
        parser.error(f"找不到音檔：{args.input}")
    if not 0 <= args.capo <= args.max_fret:
        parser.error("--capo 必須介於 0 與 --max-fret 之間")
    if args.max_fret < 1 or args.max_stretch < 0:
        parser.error("--max-fret 必須至少為 1，--max-stretch 不可為負數")
    if args.candidate_limit < 1:
        parser.error("--candidate-limit 必須至少為 1")
    for name in ("onset_threshold", "frame_threshold"):
        if not 0.0 <= getattr(args, name) <= 1.0:
            parser.error(f"--{name.replace('_', '-')} 必須介於 0 與 1")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(args, parser)
    input_path = args.input.expanduser().resolve()
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else Path("basic_pitch_output") / f"{input_path.stem}.tab.json"
    )
    midi_path = (
        args.midi_output.expanduser().resolve()
        if args.midi_output
        else output_path.with_suffix("").with_suffix(".mid")
    )
    tuning = TUNINGS[args.tuning]

    try:
        # Basic Pitch probes every optional runtime at import time. Silence warnings
        # about runtimes we intentionally did not install; Core ML remains enabled.
        previous_logging_disable = logging.root.manager.disable
        logging.disable(logging.WARNING)
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="pkg_resources is deprecated as an API.*",
                    category=UserWarning,
                )
                from basic_pitch import ICASSP_2022_MODEL_PATH
                from basic_pitch.inference import predict
        finally:
            logging.disable(previous_logging_disable)

        print(f"Basic Pitch 音訊轉 MIDI：{input_path.name}")
        started = time.perf_counter()
        model_output, midi_data, note_events = predict(
            input_path,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=args.onset_threshold,
            frame_threshold=args.frame_threshold,
            minimum_note_length=args.minimum_note_length,
            minimum_frequency=midi_to_hz(min(tuning) + args.capo),
            maximum_frequency=midi_to_hz(max(tuning) + args.max_fret),
            multiple_pitch_bends=True,
        )
        if args.save_model_output:
            import numpy as np
            from basic_pitch.note_creation import model_frames_to_time

            cache_path = args.save_model_output.expanduser()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            # Store plain arrays, not pickled objects; use the model's corrected
            # time axis (a constant hop alone drifts at inference-window joins).
            with cache_path.open("wb") as cache_file:
                np.savez_compressed(
                    cache_file,
                    **model_output,
                    times=model_frames_to_time(len(model_output["note"])),
                    source_path=str(input_path),
                )
            print(f"模型訊號：{cache_path.resolve()}")
        print(f"指板全曲最佳化：{len(note_events)} 個 MIDI notes")
        events, diagnostics = create_tab_events(
            note_events,
            tuning=tuning,
            max_fret=args.max_fret,
            capo=args.capo,
            onset_tolerance=args.onset_tolerance,
            max_stretch=args.max_stretch,
            candidate_limit=args.candidate_limit,
        )
        elapsed = time.perf_counter() - started
        write_outputs(
            input_path,
            output_path,
            midi_path,
            midi_data,
            note_events,
            events,
            diagnostics,
            args,
            tuning,
            Path(ICASSP_2022_MODEL_PATH),
            elapsed,
        )
        print(f"完成：{len(events)} 個 TAB 事件")
        print(f"MIDI：{midi_path.resolve()}")
        print(f"TAB JSON：{output_path.resolve()}")
        return 0
    except Exception as exc:  # noqa: BLE001 - present dependency errors as CLI output
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
