import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "./api.js";

describe("apiRequest", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns JSON for successful responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })));
    await expect(apiRequest("/api/test")).resolves.toEqual({ ok: true });
  });

  it("maps the stable API envelope to ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: "FAILED", message: "Nope", details: { field: "stem" } },
    }), { status: 422, headers: { "content-type": "application/json" } })));
    const error = await apiRequest("/api/test").catch((reason) => reason);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code: "FAILED", status: 422, details: { field: "stem" } });
  });
});
