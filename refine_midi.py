"""Conservative refinement of a single-guitar Basic Pitch transcription.

Write separate diagnostic previews; never overwrite the input. MIDI velocity is
only a proxy for Basic Pitch activation, not a calibrated probability. Joining
fragments requires the original model evidence, not just a short time gap.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path

import numpy as np
import pretty_midi

from basic_pitch_tab import MidiNote, TUNINGS, create_tab_events, positions_for_pitch


@dataclass(frozen=True)
class Settings:
    weak_amplitude: float = 0.40
    short_seconds: float = 0.18
    max_gap_seconds: float = 0.08
    max_onset: float = 0.25
    min_bridge_activation: float = 0.20
    max_frame_rise: float = 0.08


@dataclass
class Evidence:
    times: np.ndarray
    frames: np.ndarray
    onsets: np.ndarray

    def __post_init__(self):
        if (self.times.ndim != 1 or len(self.times) < 2
                or self.frames.shape != (len(self.times), 88)
                or self.onsets.shape != self.frames.shape
                or not all(np.isfinite(x).all() for x in (self.times, self.frames, self.onsets))
                or not (np.diff(self.times) > 0).all()):
            raise ValueError("Invalid model evidence: expected increasing times and finite N×88 arrays")

    def supports_join(self, before: MidiNote, after: MidiNote, settings: Settings):
        pitch = after.pitch - 21
        if not 0 <= pitch < 88:
            return False, {"reason": "outside_model_range"}
        # Include neighboring frames even for a zero-length gap. Use actual
        # model times rather than assuming a constant hop across window joins.
        if before.end < self.times[0] or after.start + 0.025 > self.times[-1]:
            return False, {"reason": "outside_evidence"}
        bridge = (self.times >= before.end - 0.015) & (self.times <= after.start + 0.015)
        attack = (self.times >= after.start - 0.025) & (self.times <= after.start + 0.025)
        if not bridge.any() or not attack.any():
            return False, {"reason": "missing_frames"}
        column = self.frames[:, pitch]
        # Frame rises protect re-attacks inferred from activation differences,
        # even if the onset head itself is weak.
        rise = np.maximum(0, np.diff(column, prepend=column[0]))
        peak = float(self.onsets[attack, pitch].max())
        support = float(np.mean(column[bridge] >= settings.min_bridge_activation))
        max_rise = float(rise[attack].max())
        details = {"onset_peak": peak, "bridge_support": support, "frame_rise": max_rise}
        return (peak < settings.max_onset and support >= 0.8
                and max_rise < settings.max_frame_rise), details


def clean_notes(notes, settings, tuning, max_fret, capo, evidence=None):
    changes = []
    retained = []
    for note in sorted(notes, key=lambda n: (n.start, n.pitch)):
        if not (math.isfinite(note.start) and math.isfinite(note.end)
                and math.isfinite(note.amplitude) and 0 <= note.start < note.end
                and 0 <= note.amplitude <= 1 and 0 <= note.pitch <= 127):
            raise ValueError("Invalid note timing, pitch or amplitude")
        reason = None
        if not positions_for_pitch(note.pitch, tuning, max_fret, capo):
            reason = "outside_selected_fretboard"
        elif note.end - note.start < settings.short_seconds and note.amplitude < settings.weak_amplitude:
            reason = "weak_and_short"
        if reason:
            changes.append({"action": "remove", "reason": reason, "note": asdict(note)})
        else:
            retained.append(note)

    by_pitch = defaultdict(list)
    for note in retained:
        by_pitch[note.pitch].append(note)
    output = []
    candidates = 0
    protected = []
    for pitch, lane in sorted(by_pitch.items()):
        merged = []
        for note in lane:
            if merged:
                before = merged[-1]
                gap = note.start - before.end
                if -1e-6 <= gap <= settings.max_gap_seconds:
                    candidates += 1
                    supported, details = (evidence.supports_join(before, note, settings)
                                          if evidence is not None
                                          else (False, {"reason": "no_model_evidence"}))
                    if supported:
                        merged[-1] = replace(before, end=note.end,
                                             amplitude=max(before.amplitude, note.amplitude), pitch_bends=())
                        changes.append({"action": "join", "pitch": pitch,
                                        "before": asdict(before), "after": asdict(note),
                                        "gap_seconds": gap, "evidence": details})
                        continue
                    protected.append({"pitch": pitch, "start": note.start,
                                      "gap_seconds": gap, "evidence": details})
            merged.append(note)
        output.extend(merged)
    return sorted(output, key=lambda n: (n.start, n.pitch)), {
        "changes": changes, "join_candidates": candidates, "unjoined_candidates": protected,
    }


def enforce_string_durations(events):
    """A new attack stops the previous note on that string, including old events.

    Operates on the chosen fingering, not a claim that this is the only fingering.
    Every shortening is recorded so a bad assignment can be found and reviewed.
    """
    lanes = defaultdict(list)
    for event in events:
        for note in event["notes"]:
            lanes[note["string"]].append(note)
    changes = []
    for string, lane in lanes.items():
        lane.sort(key=lambda n: n["start_seconds"])
        for before, after in zip(lane, lane[1:]):
            if before["end_seconds"] > after["start_seconds"]:
                changes.append({"action": "shorten_on_string", "string": string,
                                "pitch": before["midi_pitch"], "start": before["start_seconds"],
                                "old_end": before["end_seconds"], "new_end": after["start_seconds"]})
                before["end_seconds"] = after["start_seconds"]
    for event in events:
        event["offset_seconds"] = max(n["end_seconds"] for n in event["notes"])
    return changes


def make_midi(notes, name):
    # Diagnostic previews use the same program and no bends so A/B isolates
    # changes in note events. Keep original expressive MIDI untouched.
    midi = pretty_midi.PrettyMIDI(initial_tempo=120, resolution=960)
    instrument = pretty_midi.Instrument(program=4, name=name)
    for note in notes:
        if note.end <= note.start:
            raise ValueError("Fingering produced a zero-length note")
        instrument.notes.append(pretty_midi.Note(
            velocity=max(1, min(127, round(note.amplitude * 127))),
            pitch=note.pitch, start=note.start, end=note.end,
        ))
    midi.instruments.append(instrument)
    return midi


def main(argv=None):
    parser = argparse.ArgumentParser(description="保守去雜音，再經 TAB 指位回產 MIDI；只輸出新檔")
    parser.add_argument("input", type=Path, help="單一吉他聲部的 Basic Pitch MIDI")
    parser.add_argument("--output-dir", type=Path, default=Path("basic_pitch_output/refined"))
    parser.add_argument("--model-output", type=Path, help="同一音訊的 --save-model-output NPZ")
    parser.add_argument("--source-tab", type=Path, help="原始 TAB JSON；預設尋找同名 .tab.json")
    parser.add_argument("--tuning", choices=tuple(TUNINGS), default=None)
    parser.add_argument("--capo", type=int, default=None)
    parser.add_argument("--max-fret", type=int, default=None)
    parser.add_argument("--max-stretch", type=int, default=4)
    parser.add_argument("--weak-amplitude", type=float, default=0.40)
    parser.add_argument("--short-ms", type=float, default=180)
    parser.add_argument("--max-gap-ms", type=float, default=80)
    args = parser.parse_args(argv)
    try:
        source = args.input.expanduser().resolve()
        source_tab_path = (args.source_tab or source.with_suffix(".tab.json")).expanduser()
        source_tab = json.loads(source_tab_path.read_text()) if source_tab_path.is_file() else {}
        if args.source_tab and not source_tab_path.is_file():
            raise ValueError("找不到 --source-tab")
        if source_tab and Path(source_tab["midi_output"]).resolve() != source:
            raise ValueError("source TAB 的 midi_output 與輸入 MIDI 不符")
        original_tuning = source_tab.get("tuning", {})
        tuning_name = args.tuning or original_tuning.get("name", "standard")
        tuning = TUNINGS[tuning_name]
        capo = args.capo if args.capo is not None else original_tuning.get("capo", 0)
        max_fret = args.max_fret if args.max_fret is not None else original_tuning.get("max_fret", 22)
        if not 0 <= capo <= max_fret <= 36 or args.max_stretch < 0:
            raise ValueError("需要 0 ≤ capo ≤ max-fret ≤ 36，max-stretch ≥ 0")
        if not (0 <= args.weak_amplitude <= 1 and math.isfinite(args.short_ms)
                and 0 <= args.short_ms <= 1000 and 0 <= args.max_gap_ms <= 500):
            raise ValueError("清理參數超出範圍")
        settings = Settings(weak_amplitude=args.weak_amplitude,
                            short_seconds=args.short_ms / 1000, max_gap_seconds=args.max_gap_ms / 1000)
        evidence = None
        if args.model_output:
            with np.load(args.model_output.expanduser(), allow_pickle=False) as data:
                if not source_tab or str(data["source_path"]) != source_tab["input"]["path"]:
                    raise ValueError("模型 cache 與 source TAB 的音訊來源不符；請提供同一音訊的資料")
                evidence = Evidence(data["times"], data["note"], data["onset"])
        midi = pretty_midi.PrettyMIDI(str(source))
        if any(track.is_drum for track in midi.instruments):
            raise ValueError("此工具只處理單一吉他聲部，不接受含鼓組的 MIDI")
        notes = [MidiNote(n.pitch, n.start, n.end, n.velocity / 127)
                 for track in midi.instruments for n in track.notes]
        if not notes:
            raise ValueError("MIDI 沒有音符")
        cleaned, report = clean_notes(notes, settings, tuning, max_fret, capo, evidence)
        if not cleaned:
            raise ValueError("目前條件會刪除全部音符，請放寬過濾條件")
        tuples = [(n.start, n.end, n.pitch, n.amplitude, None) for n in cleaned]
        events, diagnostics = create_tab_events(tuples, tuning, max_fret, capo, 0.05, args.max_stretch, 64,
                                                sustain_aware=True)
        report["string_duration_changes"] = enforce_string_durations(events)
        playable = [MidiNote(n["midi_pitch"], n["start_seconds"], n["end_seconds"], n["amplitude"])
                    for event in events for n in event["notes"]]
        played_keys = {(n.pitch, round(n.start, 6)) for n in playable}
        report["tab_omitted_notes"] = [asdict(n) for n in cleaned
                                       if (n.pitch, round(n.start, 6)) not in played_keys]
        report.update({"source": str(source), "settings": asdict(settings),
                       "has_model_evidence": evidence is not None, "original_notes": len(notes),
                       "clean_notes": len(cleaned), "playable_notes": len(playable),
                       "original_pitch_bends": sum(len(t.pitch_bends) for t in midi.instruments),
                       "preview_pitch_bends": False, "tab_diagnostics": diagnostics})
        directory = args.output_dir.expanduser().resolve()
        paths = {name: directory / f"{source.stem}.{name}" for name in
                 ("clean.mid", "playable.mid", "playable.tab.json", "report.json")}
        for path in paths.values():
            if path.exists() or path == source:
                raise ValueError(f"保留既有檔案，請選另一個 --output-dir：{path}")
        clean_midi = make_midi(cleaned, "Clean preview")
        playable_midi = make_midi(playable, "TAB-constrained preview")
        directory.mkdir(parents=True, exist_ok=True)
        clean_midi.write(str(paths["clean.mid"]))
        playable_midi.write(str(paths["playable.mid"]))
        payload = {"format": "basic-pitch-tab-v1", "input": source_tab.get("input", {"path": ""}),
                   "midi_output": str(paths["playable.mid"]),
                   "tuning": {"name": tuning_name, "open_midi_low_to_high": list(tuning),
                              "capo": capo, "max_fret": max_fret},
                   "optimization": {"algorithm": "sustain-aware-beam-fretboard-v1+string-offsets",
                                    "max_fret_span": args.max_stretch},
                   "diagnostics": diagnostics, "refinement_report": str(paths["report.json"]),
                   "events": events}
        paths["playable.tab.json"].write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        paths["report.json"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        removed = sum(c["action"] == "remove" for c in report["changes"])
        joined = sum(c["action"] == "join" for c in report["changes"])
        print(f"原始 {len(notes)} → 清理 {len(cleaned)} → TAB {len(playable)} notes")
        print(f"移除 {removed}，接續 {joined}，同弦延音調整 {len(report['string_duration_changes'])}")
        if evidence is None:
            print("沒有模型訊號：已跳過斷點合併，保留重複撥弦。")
        for path in paths.values():
            print(path)
        return 0
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"錯誤：{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
