import { describe, expect, it } from "vitest";

import { acceleratorLabel, queuedHint } from "./accelerator.js";

describe("acceleratorLabel", () => {
  it.each([
    [{ accelerator: { backend: "cuda", name: "NVIDIA GeForce RTX 5090" } }, "NVIDIA CUDA · NVIDIA GeForce RTX 5090"],
    [{ accelerator: { backend: "mps", name: "Apple M3 Max" } }, "Apple MPS · Apple M3 Max"],
    [{ accelerator: { backend: "cpu", name: null } }, "CPU"],
  ])("labels %j", (diagnostics, label) => {
    expect(acceleratorLabel(diagnostics)).toBe(label);
  });

  it("returns null when the job has not reported a device", () => {
    expect(acceleratorLabel({})).toBeNull();
    expect(acceleratorLabel(undefined)).toBeNull();
  });
});

describe("queuedHint", () => {
  it("only explains queued jobs", () => {
    expect(queuedHint({ status: "QUEUED" })).toMatch(/worker/);
    expect(queuedHint({ status: "RUNNING" })).toBeNull();
  });
});
