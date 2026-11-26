import { describe, expect, it } from "vitest";

import { adjustedFret, basename, normalizeTab } from "./tab-normalizer.js";

describe("tab normalizer", () => {
  it("normalizes, filters, and sorts playable events", () => {
    const result = normalizeTab({
      format: "fretflow-tab-v1",
      input: { path: "/music/track.wav", duration_seconds: 4 },
      tuning: { capo: 20 },
      events: [
        { onset_seconds: 2, offset_seconds: 2.5, notes: [{ string: 9, fret: 1 }] },
        { onset_seconds: 1, offset_seconds: 1.4, notes: [{ string: 2, fret: 3, midi_pitch: 62 }] },
        { onset_seconds: 0.25, notes: [{ string: 6, fret: 0, end_seconds: 0.6 }] },
      ],
    });

    expect(result).toMatchObject({ title: "track", duration: 4, capo: 12, format: "fretflow-tab-v1" });
    expect(result.groups.map((group) => group.onset)).toEqual([0.25, 1]);
  });

  it("rejects malformed or empty event collections", () => {
    expect(() => normalizeTab({})).toThrow("events array");
    expect(() => normalizeTab({ events: [] })).toThrow("no playable tab events");
  });

  it("formats filenames and capo-relative frets", () => {
    expect(basename("C:\\music\\solo.tab.json")).toBe("solo");
    expect(adjustedFret(7, 2)).toBe("5");
    expect(adjustedFret(1, 2)).toBe("×");
  });
});
