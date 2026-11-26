import { describe, expect, it } from "vitest";

import { escapeHtml, statusInfo } from "./app-shell.js";

describe("app shell formatters", () => {
  it("escapes user-provided song metadata", () => {
    expect(escapeHtml('<script data-x="1">&')).toBe("&lt;script data-x=&quot;1&quot;&gt;&amp;");
  });

  it("maps known and unknown statuses without decorative copy", () => {
    expect(statusInfo("SUCCEEDED")).toEqual(["Ready", "good"]);
    expect(statusInfo("CUSTOM")).toEqual(["CUSTOM", ""]);
  });
});
