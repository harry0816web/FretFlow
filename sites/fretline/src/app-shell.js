import { acceleratorLabel, queuedHint } from "./accelerator.js";
import {
  completeUpload,
  createSeparation,
  createSong,
  createTab,
  deleteSong,
  getSeparation,
  getSong,
  getSongs,
  getStems,
  getStemTypes,
  getTab,
  getTabs,
  uploadSong,
} from "./api.js";
import { parseRoute, songRoute, tabRoute } from "./router.js";

const STATUS = {
  UPLOADING: ["Uploading", "active"],
  SEPARATING: ["Separating", "active"],
  READY: ["Ready", "good"],
  PARTIAL_FAILED: ["Partial", "warn"],
  FAILED: ["Failed", "bad"],
  QUEUED: ["Queued", "active"],
  RUNNING: ["Processing", "active"],
  SUCCEEDED: ["Ready", "good"],
};
const STEM_LABEL = {
  "acoustic-guitar": "Acoustic guitar",
  "electric-guitar": "Electric guitar",
  bass: "Bass",
  drums: "Drums",
  vocal: "Vocals",
};

export function escapeHtml(value = "") {
  return String(value).replace(/[&<>"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);
}

export function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en", { year: "numeric", month: "short", day: "numeric" }).format(new Date(value));
}

/** Render seconds as m:ss (or h:mm:ss); null when the duration is unknown. */
export function formatDuration(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return null;
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

export function statusInfo(status) {
  return STATUS[status] || [status || "Unknown", ""];
}

export function startApp(player) {
  const views = Object.fromEntries([...document.querySelectorAll("[data-view]")].map((view) => [view.dataset.view, view]));
  const transport = document.getElementById("transport");
  const search = document.getElementById("songSearch");
  const statusFilter = document.getElementById("songStatusFilter");
  const tabSearch = document.getElementById("tabSearch");
  const tabStatus = document.getElementById("tabStatusFilter");
  let renderToken = 0;
  let loadedTab = null;

  function activate(name) {
    Object.entries(views).forEach(([key, view]) => { view.hidden = key !== name; });
    const isPlayer = name === "tab";
    transport.hidden = !isPlayer;
    document.body.classList.toggle("player-open", isPlayer);
    document.querySelectorAll("[data-nav]").forEach((link) => {
      const active = link.dataset.nav === name || (name === "song" && link.dataset.nav === "library") || (name === "tab" && link.dataset.nav === "tabs");
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
    });
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  async function renderRoute() {
    const token = ++renderToken;
    const route = parseRoute();
    if (route.name === "not-found") { location.hash = "#/library"; return; }
    activate(route.name);
    try {
      if (route.name === "library") await renderLibrary(token);
      if (route.name === "separate") await renderStemChoices();
      if (route.name === "song") await renderSong(route.params.songId, token);
      if (route.name === "tabs") await renderTabs(token);
      if (route.name === "tab") await renderPlayer(route.params.tabId, token);
    } catch (error) {
      player.toast(error.message, true);
    }
  }

  async function renderLibrary(token = renderToken) {
    const list = document.getElementById("songList");
    list.innerHTML = '<div class="empty-state">Loading…</div>';
    const songs = await getSongs({ search: search.value.trim(), status: statusFilter.value });
    if (token !== renderToken) return;
    if (!songs.length) {
      list.innerHTML = '<div class="empty-state"><strong>No songs yet</strong><span>Add a song to get started.</span></div>';
      return;
    }
    list.innerHTML = songs.map((song, index) => {
      const [label, tone] = statusInfo(song.status);
      return `<a class="record-row" href="${songRoute(song.song_id)}"><span class="record-index">${String(index + 1).padStart(2, "0")}</span><span class="record-main"><strong>${escapeHtml(song.title)}</strong><small>${escapeHtml(song.source_filename)}</small></span><span class="status-mark" data-tone="${tone}">${label}</span><span class="record-meta">${[formatDuration(song.duration_seconds), formatDate(song.created_at)].filter(Boolean).join(" · ")}</span></a>`;
    }).join("");
  }

  async function renderStemChoices() {
    const container = document.getElementById("stemChoices");
    if (container.childElementCount) return;
    const stems = await getStemTypes();
    container.innerHTML = stems.map((stem) => `<label class="stem-choice"><input type="checkbox" name="stem" value="${stem.value}" ${stem.default_selected ? "checked" : ""} /><span>${stem.tab_eligible ? "TAB READY" : "STEM ONLY"}</span><strong>${STEM_LABEL[stem.value]}</strong></label>`).join("");
  }

  async function renderSong(songId, token) {
    const detail = document.getElementById("songDetail");
    detail.innerHTML = '<div class="empty-state">Loading…</div>';
    const [song, stems, tabs] = await Promise.all([getSong(songId), getStems(songId), getTabs()]);
    if (token !== renderToken) return;
    const jobId = sessionStorage.getItem(`fretflow-job:${songId}`);
    let job = null;
    if (jobId) { try { job = await getSeparation(jobId); } catch { sessionStorage.removeItem(`fretflow-job:${songId}`); } }
    const [statusLabel, tone] = statusInfo(job?.status || song.status);
    const tabByStem = new Map(tabs.map((tab) => [tab.stem_id, tab]));
    detail.innerHTML = `<header class="detail-header"><div><p class="kicker">SONG</p><h1>${escapeHtml(song.title)}</h1><div class="detail-meta"><span>${escapeHtml(song.source_filename)}</span>${formatDuration(song.duration_seconds) ? `<span>${formatDuration(song.duration_seconds)}</span>` : ""}<span>${formatDate(song.created_at)}</span><span class="status-mark" data-tone="${tone}">${statusLabel}</span>${acceleratorLabel(job?.diagnostics) ? `<span class="accelerator-mark">${escapeHtml(acceleratorLabel(job.diagnostics))}</span>` : ""}</div></div><div class="detail-header-actions"><button class="button" id="deleteSongButton" type="button">Delete</button></div></header>${job && !["SUCCEEDED", "FAILED"].includes(job.status) ? `<div class="job-progress"><span>${escapeHtml(queuedHint(job) ?? job.stage)}</span><progress max="100" value="${job.progress_percent}"></progress><span>${job.progress_percent}%</span></div>` : ""}<section class="stem-section"><header><h2>Stems</h2><span>${stems.length}</span></header><div id="stemRows">${stems.length ? stems.map((stem) => stemRow(stem, tabByStem.get(stem.stem_id))).join("") : '<div class="empty-state"><strong>Processing stems</strong></div>'}</div></section>`;
    detail.querySelector("#deleteSongButton").addEventListener("click", async () => {
      if (!confirm(`Delete “${song.title}” and its files?`)) return;
      await deleteSong(songId); location.hash = "#/library";
    });
    detail.querySelectorAll("[data-create-tab]").forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true; button.textContent = "Creating…";
      try { const tab = await createTab(button.dataset.createTab); location.hash = tabRoute(tab.tab_id); }
      catch (error) { player.toast(error.message, true); button.disabled = false; button.textContent = "Create tab"; }
    }));
    if (job && !["SUCCEEDED", "FAILED"].includes(job.status)) setTimeout(() => { if (parseRoute().params.songId === songId) renderSong(songId, renderToken); }, 1800);
  }

  function stemRow(stem, tab) {
    const [label, tone] = statusInfo(stem.status);
    const action = stem.tab_eligible ? (tab ? `<a class="small-action" href="${tabRoute(tab.tab_id)}">Open tab</a>` : `<button class="small-action" type="button" data-create-tab="${stem.stem_id}">Create tab</button>`) : '<span class="record-meta">—</span>';
    return `<article class="stem-row"><div><h3>${STEM_LABEL[stem.stem_type] || escapeHtml(stem.stem_type)}</h3><span class="status-mark" data-tone="${tone}">${label}</span></div><span class="record-meta">${[formatDuration(stem.duration_seconds), stem.sample_rate ? `${stem.sample_rate / 1000} kHz` : null].filter(Boolean).join(" · ") || "Audio"}</span><audio controls preload="none" src="${stem.artifact_url}"></audio>${action}</article>`;
  }

  async function renderTabs(token = renderToken) {
    const list = document.getElementById("tabList");
    list.innerHTML = '<div class="empty-state">Loading…</div>';
    const [tabs, songs] = await Promise.all([getTabs(tabStatus.value), getSongs()]);
    if (token !== renderToken) return;
    const titles = new Map(songs.map((song) => [song.song_id, song.title]));
    const query = tabSearch.value.trim().toLowerCase();
    const filtered = tabs.filter((tab) => `${titles.get(tab.song_id) || ""} ${tab.tuning}`.toLowerCase().includes(query));
    if (!filtered.length) { list.innerHTML = '<div class="empty-state"><strong>No tabs yet</strong><span>Create one from a guitar stem.</span></div>'; return; }
    list.innerHTML = filtered.map((tab, index) => {
      const [label, tone] = statusInfo(tab.status);
      return `<a class="record-row" href="${tabRoute(tab.tab_id)}"><span class="record-index">${String(index + 1).padStart(2, "0")}</span><span class="record-main"><strong>${escapeHtml(titles.get(tab.song_id) || "Untitled")}</strong><small>${escapeHtml(tab.tuning)} · capo ${tab.capo} · ${tab.event_count} events</small></span><span class="status-mark" data-tone="${tone}">${label}</span><span class="record-meta">${tab.max_fret} frets</span></a>`;
    }).join("");
  }

  async function renderPlayer(tabId, token) {
    if (tabId === "demo") { if (loadedTab !== "demo") { loadedTab = "demo"; await player.loadDemo(); } return; }
    const tab = await getTab(tabId);
    if (token !== renderToken) return;
    document.getElementById("playerPageTitle").textContent = tab.status === "SUCCEEDED" ? "Tab player" : "Preparing tab";
    document.getElementById("playerPageMeta").textContent = `${tab.tuning} · capo ${tab.capo} · ${statusInfo(tab.status)[0]}`;
    if (["QUEUED", "RUNNING"].includes(tab.status)) { setTimeout(() => { if (parseRoute().params.tabId === tabId) renderPlayer(tabId, renderToken); }, 1600); return; }
    if (tab.status === "FAILED") { player.toast(tab.error_message || "Tab creation failed", true); return; }
    if (loadedTab === tabId) return;
    const stems = await getStems(tab.song_id);
    const stem = stems.find((item) => item.stem_id === tab.stem_id);
    loadedTab = tabId;
    await player.loadRemote({ tabUrl: tab.tab_url, midiUrl: tab.midi_url, audioUrl: stem?.artifact_url, title: document.getElementById("playerPageMeta").textContent });
  }

  document.getElementById("separationFile").addEventListener("change", (event) => {
    const file = event.target.files[0];
    document.getElementById("separationFileName").textContent = file?.name || "MP3, WAV, M4A, or FLAC";
    const title = document.getElementById("separationTitle");
    if (file && !title.value) title.value = file.name.replace(/\.[^.]+$/, "");
  });
  document.getElementById("separationForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = document.getElementById("separationFile").files[0];
    const stems = [...document.querySelectorAll('input[name="stem"]:checked')].map((input) => input.value);
    const validation = document.getElementById("stemValidation");
    if (!file || !stems.length) { validation.textContent = !file ? "Choose an audio file." : "Select at least one stem."; validation.classList.add("error"); return; }
    validation.classList.remove("error");
    const button = event.currentTarget.querySelector('button[type="submit"]');
    const progress = document.getElementById("uploadProgress");
    button.disabled = true;
    try {
      progress.textContent = "Creating song…";
      const song = await createSong({ title: document.getElementById("separationTitle").value, source_filename: file.name, media_type: file.type || "audio/mpeg" });
      progress.textContent = "Uploading…"; await uploadSong(song.song_id, file);
      progress.textContent = "Validating…"; await completeUpload(song.song_id);
      progress.textContent = "Starting separation…";
      const job = await createSeparation(song.song_id, { requested_stems: stems, auto_tab: document.getElementById("autoTab").checked });
      sessionStorage.setItem(`fretflow-job:${song.song_id}`, job.job_id);
      location.hash = songRoute(song.song_id);
      event.currentTarget.reset();
    } catch (error) { player.toast(error.message, true); progress.textContent = "Upload failed. Try again."; }
    finally { button.disabled = false; }
  });

  let searchTimer;
  search.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => renderLibrary(), 220); });
  statusFilter.addEventListener("change", () => renderLibrary());
  tabSearch.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => renderTabs(), 180); });
  tabStatus.addEventListener("change", () => renderTabs());
  window.addEventListener("hashchange", renderRoute);
  if (!location.hash) location.hash = "#/library"; else renderRoute();
}
