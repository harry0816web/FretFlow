import path from "node:path";

import { expect, test } from "@playwright/test";

const now = "2026-10-27T12:00:00Z";

test("uploads audio, separates stems, creates a tab, and opens the player", async ({ page }) => {
  let song = null;
  let stems = [];
  let tabs = [];
  let separationRequest = null;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const json = (body, status = 200) => route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

    if (method === "GET" && url.pathname === "/api/stem-types") {
      return json([
        { value: "acoustic-guitar", tab_eligible: true, default_selected: true },
        { value: "electric-guitar", tab_eligible: true, default_selected: true },
        { value: "bass", tab_eligible: false, default_selected: false },
        { value: "drums", tab_eligible: false, default_selected: false },
        { value: "vocal", tab_eligible: false, default_selected: false },
      ]);
    }
    if (method === "POST" && url.pathname === "/api/songs") {
      const payload = request.postDataJSON();
      song = {
        song_id: "song-1",
        title: payload.title,
        source_filename: payload.source_filename,
        status: "UPLOADING",
        created_at: now,
      };
      return json(song, 201);
    }
    if (method === "POST" && url.pathname === "/api/songs/song-1/upload") {
      return json({ song_id: "song-1", artifact_key: "songs/song-1/source/source.mp3", size_bytes: 42 });
    }
    if (method === "POST" && url.pathname === "/api/songs/song-1/upload-complete") {
      song.status = "READY";
      return json(song);
    }
    if (method === "POST" && url.pathname === "/api/songs/song-1/separations") {
      separationRequest = request.postDataJSON();
      song.status = "READY";
      stems = separationRequest.requested_stems.map((stemType, index) => ({
        stem_id: `stem-${index + 1}`,
        song_id: song.song_id,
        stem_type: stemType,
        status: "READY",
        tab_eligible: stemType.includes("guitar"),
        sample_rate: 44100,
        artifact_url: `/assets/demo.mp3?stem=${stemType}`,
      }));
      if (separationRequest.auto_tab) {
        tabs = [{
          tab_id: "tab-1",
          song_id: song.song_id,
          stem_id: "stem-1",
          status: "RUNNING",
          tuning: "standard",
          capo: 0,
          max_fret: 24,
          event_count: 0,
        }];
      }
      return json({ job_id: "job-1", song_id: song.song_id, status: "SUCCEEDED", stage: "complete", progress_percent: 100 }, 201);
    }
    if (method === "GET" && url.pathname === "/api/songs/song-1") return json(song);
    if (method === "GET" && url.pathname === "/api/songs/song-1/stems") return json(stems);
    if (method === "GET" && url.pathname === "/api/separations/job-1") {
      return json({ job_id: "job-1", song_id: song.song_id, status: "SUCCEEDED", stage: "complete", progress_percent: 100 });
    }
    if (method === "GET" && url.pathname === "/api/tabs/tab-1") return json(tabs[0]);
    if (method === "GET" && url.pathname === "/api/tabs") return json(tabs);
    if (method === "GET" && url.pathname === "/api/songs") return json(song ? [song] : []);
    return json({ error: { code: "NOT_MOCKED", message: `${method} ${url.pathname}`, details: {} } }, 404);
  });

  await page.goto("/#/separate");
  await expect(page.getByRole("heading", { name: "Separate audio" })).toBeVisible();
  await page.locator("#separationFile").setInputFiles(path.resolve("public/assets/demo.mp3"));
  await page.getByLabel("Title").fill("Practice Song");
  await page.getByLabel("Create guitar tab").check();
  await page.getByRole("button", { name: "Start" }).click();

  await expect(page).toHaveURL(/#\/songs\/song-1$/);
  await expect(page.getByRole("heading", { name: "Practice Song" })).toBeVisible();
  await expect(page.locator("#songDetail").getByRole("heading", { name: "Acoustic guitar" })).toBeVisible();
  expect(separationRequest).toEqual({
    requested_stems: ["acoustic-guitar", "electric-guitar"],
    auto_tab: true,
  });

  await page.getByRole("link", { name: "Open tab" }).first().click();
  await expect(page).toHaveURL(/#\/tabs\/tab-1$/);
  await expect(page.getByRole("heading", { name: "Preparing tab" })).toBeVisible();
  await expect(page.getByText("standard · capo 0 · Processing")).toBeVisible();
});
