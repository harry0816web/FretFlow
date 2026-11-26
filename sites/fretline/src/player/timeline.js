import { clamp, number } from "./tab-normalizer.js";

export function formatTime(seconds, millis = false) {
  const value = Math.max(0, number(seconds));
  const totalMilliseconds = Math.round(value * 1000);
  const minutes = Math.floor(totalMilliseconds / 60000);
  const wholeSeconds = Math.floor((totalMilliseconds % 60000) / 1000);
  const base = `${String(minutes).padStart(2, "0")}:${String(wholeSeconds).padStart(2, "0")}`;
  if (!millis) return base;
  return `${base}.${String(totalMilliseconds % 1000).padStart(3, "0")}`;
}

export function findPreviousIndex(groups, time, tolerance = 0.0005) {
  let low = 0;
  let high = groups.length - 1;
  let result = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (groups[middle].onset <= time + tolerance) {
      result = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return result;
}

export function playbackFrame(groups, time, releaseTolerance = 0.03) {
  const previous = findPreviousIndex(groups, time);
  const active = previous >= 0 && time <= groups[previous].offset + releaseTolerance
    ? previous
    : -1;
  const next = previous + 1 < groups.length ? previous + 1 : -1;
  return { active, next };
}

export function linePosition(time, secondsPerLine, lineCount) {
  if (lineCount <= 0) return { lineIndex: -1, progress: 0 };
  const lineIndex = clamp(Math.floor(time / secondsPerLine), 0, lineCount - 1);
  const progress = clamp((time - lineIndex * secondsPerLine) / secondsPerLine, 0, 1);
  return { lineIndex, progress };
}
