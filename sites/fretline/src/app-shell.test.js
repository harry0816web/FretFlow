import { describe, expect, it } from "vitest";

import { escapeHtml, formatDuration, statusInfo } from "./app-shell.js";

describe("app shell formatters", () => {
  it("escapes user-provided song metadata", () => {
    expect(escapeHtml('<script data-x="1">&')).toBe("&lt;script data-x=&quot;1&quot;&gt;&amp;");
  });

  it("maps known and unknown statuses without decorative copy", () => {
    expect(statusInfo("SUCCEEDED")).toEqual(["Ready", "good"]);
    expect(statusInfo("CUSTOM")).toEqual(["CUSTOM", ""]);
  });

  it.each([
    [30.4, "0:30"],
    [220.47, "3:40"],
    [3725, "1:02:05"],
    [null, null],
    [0, null],
    [Number.NaN, null],
  ])("formats duration %s as %s", (seconds, text) => {
    expect(formatDuration(seconds)).toBe(text);
  });
});
