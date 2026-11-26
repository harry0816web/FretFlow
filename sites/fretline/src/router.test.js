import { describe, expect, it } from "vitest";

import { parseRoute, songRoute, tabRoute } from "./router.js";

describe("parseRoute", () => {
  it.each([
    ["#/library", { name: "library", params: {} }],
    ["#/separate", { name: "separate", params: {} }],
    ["#/songs/song-1", { name: "song", params: { songId: "song-1" } }],
    ["#/tabs", { name: "tabs", params: {} }],
    ["#/tabs/tab-1", { name: "tab", params: { tabId: "tab-1" } }],
  ])("parses %s", (hash, route) => {
    expect(parseRoute(hash)).toEqual(route);
  });

  it("uses the library for an empty hash and rejects unknown routes", () => {
    expect(parseRoute("").name).toBe("library");
    expect(parseRoute("#/unknown").name).toBe("not-found");
  });
});

describe("route builders", () => {
  it("encodes identifiers", () => {
    expect(songRoute("a/b")).toBe("#/songs/a%2Fb");
    expect(tabRoute("tab one")).toBe("#/tabs/tab%20one");
  });

  it("requires an identifier", () => {
    expect(() => songRoute("")).toThrow("songId is required");
    expect(() => tabRoute()).toThrow("tabId is required");
  });
});
