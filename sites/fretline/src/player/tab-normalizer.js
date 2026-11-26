export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

export function number(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function basename(path = "") {
  return path
    .replace(/\\/g, "/")
    .split("/")
    .pop()
    ?.replace(/\.tab\.json$/i, "")
    .replace(/\.[^.]+$/, "") || "Untitled";
}

export function normalizeTab(payload) {
  if (!payload || !Array.isArray(payload.events)) {
    throw new Error("The JSON file has no events array.");
  }

  const groups = payload.events
    .map((event, index) => {
      const onset = number(event.onset_seconds, NaN);
      if (!Number.isFinite(onset) || !Array.isArray(event.notes)) return null;
      const notes = event.notes
        .map((note) => ({
          string: Math.round(number(note.string)),
          fret: Math.round(number(note.fret)),
          pitch: number(note.midi_pitch, NaN),
          end: number(note.end_seconds, number(event.offset_seconds, onset + 0.35)),
        }))
        .filter((note) => note.string >= 1 && note.string <= 6 && note.fret >= 0);
      if (!notes.length) return null;
      return {
        onset,
        offset: number(event.offset_seconds, Math.max(...notes.map((note) => note.end))),
        notes,
        index,
      };
    })
    .filter(Boolean)
    .sort((left, right) => left.onset - right.onset || left.index - right.index);

  if (!groups.length) throw new Error("The JSON file has no playable tab events.");
  return {
    groups,
    title: basename(payload.input?.path || payload.midi_output || ""),
    duration: Math.max(number(payload.input?.duration_seconds), groups.at(-1).offset),
    capo: clamp(Math.round(number(payload.tuning?.capo)), 0, 12),
    format: payload.format || "TAB JSON",
  };
}

export function adjustedFret(fret, capo) {
  const result = fret - capo;
  return result < 0 ? "×" : String(result);
}
