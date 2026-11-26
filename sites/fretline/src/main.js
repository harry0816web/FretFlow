import { Sequencer, WorkletSynthesizer } from "spessasynth_lib";
import workletUrl from "spessasynth_lib/dist/spessasynth_processor.min.js?url";
import { adjustedFret, basename, clamp, normalizeTab, number } from "./player/tab-normalizer.js";
import { formatTime, linePosition, playbackFrame } from "./player/timeline.js";

const DISPLAY_STRINGS = [6, 5, 4, 3, 2, 1];
const STRING_LABELS = { 1: "E", 2: "A", 3: "D", 4: "G", 5: "B", 6: "e" };
const DEMO = {
  tab: "/assets/demo.tab.json",
  midi: "/assets/demo.mid",
  audio: "/assets/demo.mp3",
};
const SOUND_FONT_PARTS = [
  "/assets/GeneralUserGSv1.471.sf2.part-aa",
  "/assets/GeneralUserGSv1.471.sf2.part-ab",
];

const state = {
  groups: [],
  title: "",
  tabDuration: 0,
  audioDuration: 0,
  midiDuration: 0,
  audioUrl: null,
  mode: "audio",
  speed: 1,
  midiOffset: Number(localStorage.getItem("fretline-midi-offset") || 0) / 1000,
  capo: 0,
  secondsPerLine: 8,
  playing: false,
  looping: false,
  follow: true,
  activeIndex: -1,
  nextIndex: -1,
  currentLine: -1,
  userSeeking: false,
  raf: 0,
  lastSync: 0,
  scrollGuardUntil: 0,
  midiBinary: null,
  midiName: "",
  synthPromise: null,
  context: null,
  synth: null,
  sequencer: null,
  midiGain: null,
  toastTimer: 0,
};

const el = Object.fromEntries([
  "audio", "audioDrop", "audioInput", "audioName", "audioState", "audioVolume", "audioVolumeValue",
  "capo", "capoValue", "currentNotes", "currentTime", "demoButton", "durationTime", "engineDot",
  "engineStatus", "followButton", "lineSeconds", "lineSecondsValue", "loopButton", "midiDrop",
  "midiInput", "midiName", "midiOffset", "midiOffsetValue", "midiState", "midiVolume",
  "midiVolumeValue", "modeSwitch", "nextTime", "nowTime", "playButton", "projectStatus", "scoreEmpty",
  "scoreMeta", "scoreTitle", "seek", "speed", "tabDrop", "tabInput", "tabName", "tabPages", "tabState",
  "toast", "transportMode",
].map((id) => [id, document.getElementById(id)]));

function showToast(message, error = false) {
  clearTimeout(state.toastTimer);
  el.toast.textContent = message;
  el.toast.classList.toggle("error", error);
  el.toast.classList.add("show");
  state.toastTimer = setTimeout(() => el.toast.classList.remove("show"), 3300);
}

async function loadTabFile(file) {
  const normalized = normalizeTab(JSON.parse(await file.text()));
  state.groups = normalized.groups;
  state.title = normalized.title || basename(file.name);
  state.tabDuration = normalized.duration;
  state.capo = normalized.capo;
  el.capo.value = String(state.capo);
  el.capoValue.value = String(state.capo);
  el.tabName.textContent = file.name;
  el.tabState.textContent = `${state.groups.length} positions`;
  el.tabDrop.classList.add("loaded");
  el.scoreTitle.textContent = state.title;
  el.scoreMeta.textContent = `${normalized.format} · ${state.groups.length} events · ${formatTime(state.tabDuration)}`;
  renderTab();
  updateProjectStatus();
}

function setAudioFile(file) {
  if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
  state.audioUrl = URL.createObjectURL(file);
  el.audio.src = state.audioUrl;
  el.audio.load();
  el.audioName.textContent = file.name;
  el.audioState.textContent = "Loading";
  el.audioDrop.classList.add("loaded");
}

async function ensureSynth() {
  if (state.synthPromise) return state.synthPromise;
  state.synthPromise = (async () => {
    el.engineStatus.textContent = "Loading SoundFont…";
    state.context = new AudioContext({ latencyHint: "interactive" });
    await state.context.audioWorklet.addModule(workletUrl);
    state.synth = new WorkletSynthesizer(state.context);
    await state.synth.isReady;
    state.midiGain = state.context.createGain();
    state.midiGain.gain.value = number(el.midiVolume.value, .65);
    state.synth.connect(state.midiGain);
    state.midiGain.connect(state.context.destination);
    const fontParts = await Promise.all(SOUND_FONT_PARTS.map(async (url) => {
      const response = await fetch(url);
      if (!response.ok) throw new Error("Could not download the MIDI SoundFont.");
      return response.arrayBuffer();
    }));
    const font = await new Blob(fontParts).arrayBuffer();
    await state.synth.soundBankManager.addSoundBank(font, "main");
    state.sequencer = new Sequencer(state.synth);
    state.sequencer.skipToFirstNoteOn = false;
    state.sequencer.eventHandler.addEvent("songChange", "fretline-song", () => {
      state.midiDuration = state.sequencer.duration;
      setTimeout(applyMidiProgram, 0);
      updateReadyState();
      updateProjectStatus();
    });
    el.engineDot.classList.add("ready");
    el.engineStatus.textContent = "MIDI ready";
    if (state.midiBinary) loadMidiIntoSequencer();
  })().catch((error) => {
    state.synthPromise = null;
    el.engineStatus.textContent = "MIDI unavailable";
    showToast(error.message, true);
    throw error;
  });
  return state.synthPromise;
}

function applyMidiProgram() {
  if (!state.synth) return;
  state.synth.programChange(0, 4);
}

function loadMidiIntoSequencer() {
  if (!state.sequencer || !state.midiBinary) return;
  state.sequencer.pause();
  state.sequencer.loadNewSongList([{ binary: state.midiBinary.slice(0), fileName: state.midiName }]);
  el.midiState.textContent = "Ready";
  updateReadyState();
}

async function loadMidiFile(file) {
  state.midiBinary = await file.arrayBuffer();
  state.midiName = file.name;
  el.midiName.textContent = file.name;
  el.midiState.textContent = "Loading";
  el.midiDrop.classList.add("loaded");
  await ensureSynth();
  loadMidiIntoSequencer();
  updateProjectStatus();
}

async function fileFromUrl(url, name, type) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load ${name}.`);
  return new File([await response.blob()], name, { type });
}

async function loadDemo() {
  el.demoButton.disabled = true;
  el.demoButton.textContent = "Loading…";
  try {
    const [tab, midi, audio] = await Promise.all([
      fileFromUrl(DEMO.tab, "gummy-b-demo.playable.tab.json", "application/json"),
      fileFromUrl(DEMO.midi, "gummy-b-demo.playable.mid", "audio/midi"),
      fileFromUrl(DEMO.audio, "gummy-b-demo.mp3", "audio/mpeg"),
    ]);
    await Promise.all([loadTabFile(tab), loadMidiFile(midi)]);
    setAudioFile(audio);
    setMode("both");
    state.follow = true;
    updateFollowButton();
    updateLine(0, true);
    showToast("Demo loaded.");
  } catch (error) {
    showToast(error.message, true);
  } finally {
    el.demoButton.disabled = false;
    el.demoButton.textContent = "Reload demo";
  }
}

async function loadRemote({ tabUrl, midiUrl, audioUrl }) {
  if (!tabUrl || !midiUrl || !audioUrl) throw new Error("Tab files are not ready yet.");
  const [tab, midi, audio] = await Promise.all([
    fileFromUrl(tabUrl, "transcription.tab.json", "application/json"),
    fileFromUrl(midiUrl, "transcription.mid", "audio/midi"),
    fileFromUrl(audioUrl, "guitar-stem.wav", "audio/wav"),
  ]);
  await loadTabFile(tab);
  await loadMidiFile(midi);
  setAudioFile(audio);
  setMode("both");
  state.follow = true;
  updateFollowButton();
  updateLine(0, true);
  showToast("Tab loaded.");
}

function getDuration() {
  const tabDuration = state.tabDuration || 0;
  const audioDuration = modeHasAudio() ? state.audioDuration : 0;
  const midiDuration = modeHasMidi() ? Math.max(0, state.midiDuration - state.midiOffset) : 0;
  return Math.max(audioDuration, midiDuration, tabDuration);
}
function modeHasAudio() { return state.mode === "audio" || state.mode === "both"; }
function modeHasMidi() { return state.mode === "midi" || state.mode === "both"; }
function getCurrentTime() {
  if (modeHasAudio() && state.audioUrl) return number(el.audio.currentTime);
  if (modeHasMidi() && state.sequencer) return Math.max(0, number(state.sequencer.currentTime) - state.midiOffset);
  return number(el.seek.value);
}
function canPlayMode(mode = state.mode) {
  if (mode === "audio") return Boolean(state.audioUrl);
  if (mode === "midi") return Boolean(state.midiBinary && state.sequencer);
  return Boolean(state.audioUrl && state.midiBinary && state.sequencer);
}

function setMode(mode) {
  const time = getCurrentTime();
  const resume = state.playing;
  pauseAll();
  state.mode = mode;
  el.modeSwitch.querySelectorAll("button").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.mode === mode)));
  el.transportMode.textContent = mode.toUpperCase();
  seekTo(time, false);
  updateReadyState();
  if (resume && canPlayMode()) playAll();
}

async function playAll() {
  if (!canPlayMode()) {
    showToast(state.mode === "both" ? "Load both MIDI and audio first." : `Load ${state.mode === "midi" ? "MIDI" : "audio"} first.`, true);
    return;
  }
  const time = getCurrentTime() >= getDuration() - .02 ? 0 : getCurrentTime();
  if (modeHasMidi()) {
    await ensureSynth();
    await state.context.resume();
    state.sequencer.playbackRate = state.speed;
    state.sequencer.currentTime = clamp(time + state.midiOffset, 0, state.sequencer.duration || Infinity);
    state.sequencer.play();
    applyMidiProgram();
  }
  if (modeHasAudio()) {
    el.audio.playbackRate = state.speed;
    el.audio.currentTime = clamp(time, 0, el.audio.duration || Infinity);
    await el.audio.play();
  }
  state.playing = true;
  el.playButton.classList.add("playing");
  el.playButton.setAttribute("aria-label", "Pause");
  cancelAnimationFrame(state.raf);
  state.raf = requestAnimationFrame(animationLoop);
}

function pauseAll() {
  el.audio.pause();
  if (state.sequencer && !state.sequencer.paused) state.sequencer.pause();
  state.playing = false;
  el.playButton.classList.remove("playing");
  el.playButton.setAttribute("aria-label", "Play");
  cancelAnimationFrame(state.raf);
  updatePlaybackUI(true);
}

function seekTo(seconds, preservePlay = true) {
  const wasPlaying = state.playing && preservePlay;
  const target = clamp(number(seconds), 0, getDuration() || number(seconds));
  if (state.audioUrl) el.audio.currentTime = clamp(target, 0, el.audio.duration || Infinity);
  if (state.sequencer && state.midiBinary) state.sequencer.currentTime = clamp(target + state.midiOffset, 0, state.sequencer.duration || Infinity);
  el.seek.value = String(target);
  updatePlaybackUI(true);
  if (wasPlaying) {
    if (modeHasAudio() && el.audio.paused) el.audio.play();
    if (modeHasMidi() && state.sequencer.paused) state.sequencer.play();
  }
}

function renderCurrentNotes(group) {
  el.currentNotes.replaceChildren();
  if (!group) {
    const p = document.createElement("p"); p.textContent = "Waiting"; el.currentNotes.append(p); return;
  }
  [...group.notes].sort((a, b) => b.string - a.string).forEach((note) => {
    const chip = document.createElement("span"); chip.className = "note-chip";
    chip.innerHTML = `<small>${STRING_LABELS[note.string]}</small><strong>${adjustedFret(note.fret, state.capo)}</strong>`;
    el.currentNotes.append(chip);
  });
}

function renderTab() {
  el.tabPages.replaceChildren();
  if (!state.groups.length) return;
  el.scoreEmpty.hidden = true;
  el.tabPages.hidden = false;
  const duration = Math.max(state.tabDuration, state.groups.at(-1).offset);
  const lineCount = Math.ceil(duration / state.secondsPerLine);
  const fragment = document.createDocumentFragment();
  for (let lineIndex = 0; lineIndex < lineCount; lineIndex += 1) {
    const start = lineIndex * state.secondsPerLine;
    const end = Math.min(duration, start + state.secondsPerLine);
    const line = document.createElement("section");
    line.className = "tab-line"; line.dataset.line = String(lineIndex);
    line.innerHTML = `<span class="line-time">${formatTime(start)}</span><span class="line-time line-end-time">${formatTime(end)}</span><div class="string-labels">${DISPLAY_STRINGS.map((s) => `<span>${STRING_LABELS[s]}</span>`).join("")}</div><div class="staff">${DISPLAY_STRINGS.map((_, row) => `<i class="string-line" style="top:${row * 20 + 10}px"></i>`).join("")}${[.25,.5,.75].map((part) => `<i class="bar-line" style="left:${part * 100}%"></i>`).join("")}<i class="line-playhead"></i></div>`;
    fragment.append(line);
  }
  el.tabPages.append(fragment);
  const lines = [...el.tabPages.querySelectorAll(".tab-line")];
  state.groups.forEach((group, groupIndex) => {
    const lineIndex = Math.min(lines.length - 1, Math.floor(group.onset / state.secondsPerLine));
    const local = (group.onset - lineIndex * state.secondsPerLine) / state.secondsPerLine;
    const staff = lines[lineIndex].querySelector(".staff");
    group.notes.forEach((note) => {
      const button = document.createElement("button");
      button.type = "button"; button.className = "tab-note"; button.dataset.group = String(groupIndex);
      button.style.left = `${clamp(local, .006, .994) * 100}%`;
      button.style.top = `${DISPLAY_STRINGS.indexOf(note.string) * 20 + 10}px`;
      button.textContent = adjustedFret(note.fret, state.capo);
      button.title = `${formatTime(group.onset, true)} · ${STRING_LABELS[note.string]} string · fret ${adjustedFret(note.fret, state.capo)}`;
      button.addEventListener("click", () => { seekTo(group.onset); state.follow = true; updateFollowButton(); });
      staff.append(button);
    });
  });
  state.currentLine = -1;
  updatePlaybackUI(true);
}

function updateEventClasses(active, next) {
  el.tabPages.querySelectorAll(".tab-note.active,.tab-note.next").forEach((node) => node.classList.remove("active", "next"));
  if (active >= 0) el.tabPages.querySelectorAll(`[data-group="${active}"]`).forEach((node) => node.classList.add("active"));
  if (next >= 0) el.tabPages.querySelectorAll(`[data-group="${next}"]`).forEach((node) => node.classList.add("next"));
}

function updateLine(time, force = false) {
  if (!state.groups.length) return;
  const lines = [...el.tabPages.querySelectorAll(".tab-line")];
  const { lineIndex, progress } = linePosition(time, state.secondsPerLine, lines.length);
  lines.forEach((line, index) => line.classList.toggle("current", index === lineIndex));
  const playhead = lines[lineIndex]?.querySelector(".line-playhead");
  if (playhead) playhead.style.left = `${progress * 100}%`;
  if ((force || lineIndex !== state.currentLine) && state.follow && lines[lineIndex]) {
    state.scrollGuardUntil = performance.now() + 700;
    lines[lineIndex].scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
  }
  state.currentLine = lineIndex;
}

function updatePlaybackUI(force = false) {
  const time = getCurrentTime();
  const duration = getDuration();
  const { active, next } = playbackFrame(state.groups, time);
  el.currentTime.textContent = formatTime(time);
  el.nowTime.textContent = formatTime(time, true);
  el.durationTime.textContent = formatTime(duration);
  el.seek.max = String(Math.max(duration, .01));
  if (!state.userSeeking) el.seek.value = String(clamp(time, 0, duration));
  if (force || active !== state.activeIndex || next !== state.nextIndex) {
    state.activeIndex = active; state.nextIndex = next;
    updateEventClasses(active, next);
    renderCurrentNotes(active >= 0 ? state.groups[active] : null);
  }
  el.nextTime.textContent = next >= 0 ? `${Math.max(0, state.groups[next].onset - time).toFixed(2)} sec` : "—";
  updateLine(time, force);
}

function animationLoop(timestamp) {
  updatePlaybackUI();
  if (state.mode === "both" && timestamp - state.lastSync > 500 && state.sequencer) {
    state.lastSync = timestamp;
    const expected = el.audio.currentTime + state.midiOffset;
    if (Math.abs(state.sequencer.currentTime - expected) > .075) state.sequencer.currentTime = clamp(expected, 0, state.sequencer.duration || Infinity);
  }
  const ended = getCurrentTime() >= getDuration() - .025;
  if (ended && state.looping) seekTo(0);
  else if (ended) pauseAll();
  if (state.playing) state.raf = requestAnimationFrame(animationLoop);
}

function updateFollowButton() {
  el.followButton.classList.toggle("active", state.follow);
  el.followButton.setAttribute("aria-pressed", String(state.follow));
}
function updateReadyState() {
  el.playButton.disabled = !canPlayMode();
  el.seek.disabled = !getDuration();
}
function updateProjectStatus() {
  const parts = [state.groups.length ? "TAB" : null, state.midiBinary ? "MIDI" : null, state.audioUrl ? "AUDIO" : null].filter(Boolean);
  el.projectStatus.textContent = parts.length ? `${parts.join(" + ")} loaded` : "No files loaded";
  updateReadyState();
}

function setupDrop(zone, input, kind) {
  ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.remove("drag"); }));
  zone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files[0]; if (file) handleFile(kind, file);
  });
  input.addEventListener("change", () => input.files[0] && handleFile(kind, input.files[0]));
}
async function handleFile(kind, file) {
  try {
    if (kind === "tab") await loadTabFile(file);
    if (kind === "midi") await loadMidiFile(file);
    if (kind === "audio") setAudioFile(file);
    showToast(`Loaded ${file.name}`);
  } catch (error) { showToast(error.message, true); }
}

setupDrop(el.tabDrop, el.tabInput, "tab");
setupDrop(el.midiDrop, el.midiInput, "midi");
setupDrop(el.audioDrop, el.audioInput, "audio");
el.demoButton.addEventListener("click", () => {
  if (location.hash === "#/tabs/demo") loadDemo();
  else location.hash = "#/tabs/demo";
});
el.modeSwitch.addEventListener("click", (event) => { const button = event.target.closest("button[data-mode]"); if (button) setMode(button.dataset.mode); });
el.playButton.addEventListener("click", () => state.playing ? pauseAll() : playAll().catch((error) => showToast(error.message, true)));
el.audio.addEventListener("loadedmetadata", () => { state.audioDuration = number(el.audio.duration); el.audioState.textContent = formatTime(state.audioDuration); updateReadyState(); updateProjectStatus(); });
el.audio.addEventListener("ended", () => { if (!state.looping) pauseAll(); });
el.audioVolume.addEventListener("input", () => { el.audio.volume = number(el.audioVolume.value); el.audioVolumeValue.value = `${Math.round(el.audio.volume * 100)}%`; });
el.midiVolume.addEventListener("input", () => { const value = number(el.midiVolume.value); if (state.midiGain) state.midiGain.gain.value = value; el.midiVolumeValue.value = `${Math.round(value * 100)}%`; });
el.midiOffset.value = String(Math.round(state.midiOffset * 1000));
el.midiOffsetValue.value = `${Math.round(state.midiOffset * 1000)} ms`;
el.midiOffset.addEventListener("input", () => { state.midiOffset = number(el.midiOffset.value) / 1000; el.midiOffsetValue.value = `${Math.round(state.midiOffset * 1000)} ms`; localStorage.setItem("fretline-midi-offset", String(Math.round(state.midiOffset * 1000))); if (state.playing && state.sequencer) state.sequencer.currentTime = getCurrentTime() + state.midiOffset; });
el.lineSeconds.addEventListener("input", () => { state.secondsPerLine = number(el.lineSeconds.value, 8); el.lineSecondsValue.value = `${state.secondsPerLine} sec`; renderTab(); });
el.capo.addEventListener("input", () => { state.capo = Math.round(number(el.capo.value)); el.capoValue.value = String(state.capo); renderTab(); });
el.followButton.addEventListener("click", () => { state.follow = !state.follow; updateFollowButton(); if (state.follow) updateLine(getCurrentTime(), true); });
el.speed.addEventListener("change", () => { state.speed = number(el.speed.value, 1); el.audio.playbackRate = state.speed; if (state.sequencer) state.sequencer.playbackRate = state.speed; });
el.loopButton.addEventListener("click", () => { state.looping = !state.looping; el.loopButton.setAttribute("aria-pressed", String(state.looping)); if (state.sequencer) state.sequencer.loopCount = 0; });
el.seek.addEventListener("pointerdown", () => { state.userSeeking = true; });
el.seek.addEventListener("input", () => { const time = number(el.seek.value); el.currentTime.textContent = formatTime(time); el.nowTime.textContent = formatTime(time, true); updateLine(time); });
el.seek.addEventListener("change", () => { state.userSeeking = false; seekTo(el.seek.value); });
["wheel", "touchstart"].forEach((name) => window.addEventListener(name, () => {
  if (performance.now() < state.scrollGuardUntil) return;
  if (state.follow && state.groups.length) { state.follow = false; updateFollowButton(); }
}, { passive: true }));
document.addEventListener("keydown", (event) => {
  if (event.target.matches("input,select,button")) return;
  if (event.code === "Space") { event.preventDefault(); state.playing ? pauseAll() : playAll(); }
  if (event.code === "ArrowLeft") { event.preventDefault(); seekTo(getCurrentTime() - 5); }
  if (event.code === "ArrowRight") { event.preventDefault(); seekTo(getCurrentTime() + 5); }
});
window.addEventListener("beforeunload", () => { if (state.audioUrl) URL.revokeObjectURL(state.audioUrl); pauseAll(); });

updateFollowButton();
updateReadyState();
updateProjectStatus();

import("./app-shell.js").then(({ startApp }) => startApp({
  loadDemo,
  loadRemote,
  toast: showToast,
})).catch((error) => showToast(error.message, true));
