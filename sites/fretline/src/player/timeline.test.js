import { describe, expect, it } from "vitest";

import { findPreviousIndex, formatTime, linePosition, playbackFrame } from "./timeline.js";

const groups = [
  { onset: 1, offset: 1.5 },
  { onset: 2, offset: 2.25 },
  { onset: 4, offset: 4.5 },
];

describe("player timeline", () => {
  it("formats bounded timestamps", () => {
    expect(formatTime(-1)).toBe("00:00");
    expect(formatTime(65.234, true)).toBe("01:05.234");
  });

  it("finds active and next events with binary search", () => {
    expect(findPreviousIndex(groups, 0.5)).toBe(-1);
    expect(findPreviousIndex(groups, 2.1)).toBe(1);
    expect(playbackFrame(groups, 2.1)).toEqual({ active: 1, next: 2 });
    expect(playbackFrame(groups, 3)).toEqual({ active: -1, next: 2 });
  });

  it("maps time to a clamped score line", () => {
    expect(linePosition(13, 8, 3)).toEqual({ lineIndex: 1, progress: 0.625 });
    expect(linePosition(99, 8, 3)).toEqual({ lineIndex: 2, progress: 1 });
    expect(linePosition(0, 8, 0)).toEqual({ lineIndex: -1, progress: 0 });
  });
});
