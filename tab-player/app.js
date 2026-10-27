(function () {
  "use strict";

  const DISPLAY_STRINGS = [6, 5, 4, 3, 2, 1];
  const STRING_LABELS = { 1: "E", 2: "A", 3: "D", 4: "G", 5: "B", 6: "e" };
  const MIN_CANVAS_WIDTH = 920;
  const CANVAS_PADDING = 58;
  const ACTIVE_EPSILON = 0.0005;
  const ACTIVE_HOLD_SECONDS = 0.35;

  const state = {
    groups: [],
    metadata: null,
    jsonDuration: 0,
    audioDuration: 0,
    audioUrl: null,
    capo: 0,
    pixelsPerSecond: 68,
    activeIndex: -1,
    nextIndex: -1,
    followPlayback: true,
    userSeeking: false,
    rafId: 0,
    toastTimer: 0,
  };

  const elements = {};

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function safeNumber(value, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function formatClock(seconds, includeMillis = false) {
    const safe = Math.max(0, safeNumber(seconds));
    const minutes = Math.floor(safe / 60);
    const secs = Math.floor(safe % 60);
    if (!includeMillis) {
      return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
    }
    const millis = Math.floor((safe % 1) * 1000);
    return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
  }

  function basename(path) {
    if (typeof path !== "string" || !path) return "未命名樂段";
    const normalized = path.replace(/\\/g, "/");
    const filename = normalized.split("/").pop() || normalized;
    return filename
      .replace(/\.tab\.json$/i, "")
      .replace(/\.[^.]+$/, "");
  }

  function adjustedFret(fret, capo) {
    const original = Math.round(safeNumber(fret));
    const relative = original - capo;
    return {
      original,
      relative,
      impossible: relative < 0,
      text: relative < 0 ? "×" : String(relative),
    };
  }

  function normalizePayload(payload) {
    if (!payload || typeof payload !== "object" || !Array.isArray(payload.events)) {
      throw new Error("JSON 缺少 events 陣列，請選擇 Basic Pitch TAB 輸出檔。");
    }

    const normalizedEvents = payload.events
      .map((event, sourceIndex) => {
        const onset = Number(event.onset_seconds);
        if (!Number.isFinite(onset) || onset < 0 || !Array.isArray(event.notes)) return null;

        const notes = event.notes
          .map((note) => {
            const stringNumber = Number(note.string);
            const fret = Number(note.fret);
            if (!Number.isInteger(stringNumber) || stringNumber < 1 || stringNumber > 6) return null;
            if (!Number.isFinite(fret) || fret < 0) return null;
            return {
              string: stringNumber,
              fret: Math.round(fret),
              midiPitch: Number.isFinite(Number(note.midi_pitch)) ? Number(note.midi_pitch) : null,
              score: Number.isFinite(Number(note.score_uncalibrated))
                ? Number(note.score_uncalibrated)
                : (Number.isFinite(Number(note.amplitude)) ? Number(note.amplitude) : null),
            };
          })
          .filter(Boolean);

        if (!notes.length) return null;
        return {
          onset,
          notes,
          score: Number.isFinite(Number(event.score_uncalibrated))
            ? Number(event.score_uncalibrated)
            : (Number.isFinite(Number(event.score)) ? Number(event.score) : null),
          sourceIndex,
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.onset - b.onset || a.sourceIndex - b.sourceIndex);

    const onsetCandidates = Array.isArray(payload.onset_candidates)
      ? payload.onset_candidates
        .map((candidate) => Number(candidate && candidate.onset_seconds))
        .filter((onset) => Number.isFinite(onset) && onset >= 0)
        .map((onset) => ({
          onset,
          notes: [],
          score: null,
          sourceIndex: -1,
          candidate: true,
        }))
      : [];
    const timelineItems = [...onsetCandidates, ...normalizedEvents]
      .sort((a, b) => a.onset - b.onset || a.sourceIndex - b.sourceIndex);

    const groups = [];
    for (const event of timelineItems) {
      let group = groups.at(-1);
      if (!group || Math.abs(group.onset - event.onset) > ACTIVE_EPSILON) {
        group = {
          onset: event.onset,
          notesByString: new Map(),
          scores: [],
          candidate: false,
        };
        groups.push(group);
      }
      group.candidate ||= Boolean(event.candidate);
      if (event.score !== null) group.scores.push(event.score);
      for (const note of event.notes) {
        if (!group.notesByString.has(note.string)) group.notesByString.set(note.string, []);
        const candidates = group.notesByString.get(note.string);
        if (!candidates.some((candidate) => candidate.fret === note.fret)) candidates.push(note);
      }
    }

    for (const group of groups) {
      for (const candidates of group.notesByString.values()) {
        candidates.sort((a, b) => {
          const aScore = a.score === null ? -1 : a.score;
          const bScore = b.score === null ? -1 : b.score;
          return bScore - aScore || a.fret - b.fret;
        });
      }
      group.score = group.scores.length ? Math.max(...group.scores) : null;
    }

    if (!groups.length) throw new Error("JSON 中沒有可顯示的 onset 或 string / fret 事件。");

    const jsonDuration = Math.max(
      safeNumber(payload.input && payload.input.duration_seconds),
      safeNumber(payload.duration_seconds),
      groups.at(-1).onset + 2,
    );

    return {
      groups,
      duration: jsonDuration,
      title: basename(payload.input && payload.input.path),
      format: typeof payload.format === "string" ? payload.format : "TAB JSON",
      inputPath: payload.input && typeof payload.input.path === "string" ? payload.input.path : "",
      model: payload.model || null,
      rawEventCount: payload.events.length,
      decodedTimeCount: groups.filter((group) => group.notesByString.size > 0).length,
      onsetCandidateCount: onsetCandidates.length,
      diagnostics: payload.diagnostics || null,
      capo: clamp(Math.round(safeNumber(payload.tuning && payload.tuning.capo)), 0, 12),
    };
  }

  function getDuration() {
    return state.audioDuration || state.jsonDuration || 0;
  }

  function getCurrentTime() {
    return Number.isFinite(elements.audio.currentTime) ? elements.audio.currentTime : 0;
  }

  function findActiveIndex(time) {
    if (!state.groups.length || time + ACTIVE_EPSILON < state.groups[0].onset) return -1;
    let low = 0;
    let high = state.groups.length - 1;
    let result = -1;
    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      if (state.groups[mid].onset <= time + ACTIVE_EPSILON) {
        result = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    if (result < 0) return -1;
    return time - state.groups[result].onset <= ACTIVE_HOLD_SECONDS ? result : -1;
  }

  function findPreviousIndex(time) {
    if (!state.groups.length || time + ACTIVE_EPSILON < state.groups[0].onset) return -1;
    let low = 0;
    let high = state.groups.length - 1;
    let result = -1;
    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      if (state.groups[mid].onset <= time + ACTIVE_EPSILON) {
        result = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return result;
  }

  function showToast(message, isError = false) {
    clearTimeout(state.toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.toggle("error", isError);
    elements.toast.classList.add("show");
    state.toastTimer = window.setTimeout(() => elements.toast.classList.remove("show"), 3400);
  }

  function setGlobalStatus() {
    const hasJson = state.groups.length > 0;
    const hasAudio = Boolean(state.audioUrl);
    elements.statusDot.classList.toggle("ready", hasJson && hasAudio);
    if (hasJson && hasAudio) elements.globalStatus.textContent = "JSON 與音檔已就緒";
    else if (hasJson) elements.globalStatus.textContent = "還需要對應音檔";
    else if (hasAudio) elements.globalStatus.textContent = "還需要 Basic Pitch TAB JSON";
    else elements.globalStatus.textContent = "等待匯入檔案";
  }

  function createTimeRuler(duration) {
    elements.timeRuler.replaceChildren();
    const interval = state.pixelsPerSecond >= 80 ? 5 : 10;
    for (let second = 0; second <= duration; second += interval) {
      const tick = document.createElement("span");
      tick.className = "time-tick";
      tick.style.left = `${CANVAS_PADDING + second * state.pixelsPerSecond}px`;
      tick.textContent = formatClock(second);
      elements.timeRuler.append(tick);
    }
  }

  function candidateDisplay(candidates) {
    const positions = candidates.map((candidate) => adjustedFret(candidate.fret, state.capo));
    return {
      text: positions.map((position) => position.text).join("/"),
      impossible: positions.some((position) => position.impossible),
      original: positions.map((position) => position.original).join("/"),
      conflict: positions.length > 1,
    };
  }

  function renderScore() {
    if (!state.groups.length) return;

    const duration = Math.max(getDuration(), state.groups.at(-1).onset + 2);
    const canvasWidth = Math.max(MIN_CANVAS_WIDTH, duration * state.pixelsPerSecond + CANVAS_PADDING * 2);
    elements.tabCanvas.style.width = `${canvasWidth}px`;
    createTimeRuler(duration);
    elements.eventLayer.replaceChildren();

    let hasImpossible = false;
    state.groups.forEach((group, index) => {
      const eventButton = document.createElement("button");
      eventButton.className = "tab-event";
      eventButton.type = "button";
      eventButton.dataset.index = String(index);
      eventButton.style.left = `${CANVAS_PADDING + group.onset * state.pixelsPerSecond}px`;
      eventButton.setAttribute("aria-label", `${formatClock(group.onset, true)} 的指位事件`);

      if (!group.notesByString.size) {
        eventButton.classList.add("unresolved");
        eventButton.setAttribute(
          "aria-label",
          `${formatClock(group.onset, true)} 偵測到起音，但沒有 TAB`,
        );
        const marker = document.createElement("span");
        marker.className = "unresolved-marker";
        marker.setAttribute("aria-hidden", "true");
        eventButton.append(marker);
      }

      DISPLAY_STRINGS.forEach((stringNumber, rowIndex) => {
        const candidates = group.notesByString.get(stringNumber);
        if (!candidates || !candidates.length) return;
        const display = candidateDisplay(candidates);
        hasImpossible ||= display.impossible;
        const cell = document.createElement("span");
        cell.className = "fret-cell";
        if (display.impossible) cell.classList.add("impossible");
        if (display.conflict) cell.classList.add("conflict");
        cell.style.top = `${rowIndex * 48 + 24}px`;
        cell.textContent = display.text;
        cell.title = `${STRING_LABELS[stringNumber]} 弦：原始 ${display.original} 格；capo ${state.capo} 格後為 ${display.text}`;
        eventButton.append(cell);
      });

      eventButton.addEventListener("click", (event) => {
        event.stopPropagation();
        seekTo(group.onset);
        state.followPlayback = true;
        updateFollowButton();
      });
      elements.eventLayer.append(eventButton);
    });

    elements.capoAlert.hidden = !hasImpossible;
    updatePlaybackUI(true);
  }

  function currentGroupSummary(group) {
    if (!group) return [];
    return DISPLAY_STRINGS.flatMap((stringNumber) => {
      const candidates = group.notesByString.get(stringNumber);
      if (!candidates || !candidates.length) return [];
      const display = candidateDisplay(candidates);
      return [{ stringNumber, ...display }];
    });
  }

  function renderCurrentNotes(group) {
    const summary = currentGroupSummary(group);
    elements.currentNotes.replaceChildren();
    if (!summary.length) {
      const empty = document.createElement("p");
      empty.textContent = group
        ? "偵測到起音，但模型沒有產生可靠指位"
        : (state.groups.length ? "等待下一個辨識事件" : "等待第一個辨識事件");
      elements.currentNotes.append(empty);
      return;
    }

    for (const note of summary) {
      const chip = document.createElement("span");
      chip.className = "note-chip";
      if (note.impossible) chip.classList.add("impossible");
      const stringLabel = document.createElement("span");
      stringLabel.className = "chip-string";
      stringLabel.textContent = STRING_LABELS[note.stringNumber];
      const fret = document.createElement("strong");
      fret.textContent = note.text;
      const caption = document.createElement("small");
      caption.textContent = note.conflict ? "候選格位" : "相對格位";
      chip.append(stringLabel, fret, caption);
      elements.currentNotes.append(chip);
    }
  }

  function updateEventClasses(activeIndex, nextIndex) {
    elements.eventLayer.querySelectorAll(".tab-event.active, .tab-event.next").forEach((node) => {
      node.classList.remove("active", "next");
    });
    if (activeIndex >= 0) {
      const active = elements.eventLayer.querySelector(`[data-index="${activeIndex}"]`);
      if (active) active.classList.add("active");
    }
    if (nextIndex >= 0) {
      const next = elements.eventLayer.querySelector(`[data-index="${nextIndex}"]`);
      if (next) next.classList.add("next");
    }
  }

  function updatePlaybackUI(force = false) {
    const time = getCurrentTime();
    const duration = getDuration();
    const activeIndex = findActiveIndex(time);
    const previousIndex = findPreviousIndex(time);
    const nextIndex = previousIndex + 1 < state.groups.length ? previousIndex + 1 : -1;

    elements.currentTime.textContent = formatClock(time);
    elements.nowTime.textContent = formatClock(time, true);
    elements.durationTime.textContent = formatClock(duration);
    elements.seekRange.max = String(Math.max(duration, 0.01));
    if (!state.userSeeking) elements.seekRange.value = String(clamp(time, 0, duration || 0));
    elements.playhead.style.left = `${CANVAS_PADDING + time * state.pixelsPerSecond}px`;

    if (force || activeIndex !== state.activeIndex || nextIndex !== state.nextIndex) {
      state.activeIndex = activeIndex;
      state.nextIndex = nextIndex;
      updateEventClasses(activeIndex, nextIndex);
      renderCurrentNotes(activeIndex >= 0 ? state.groups[activeIndex] : null);
    }

    if (nextIndex >= 0) {
      const delta = Math.max(0, state.groups[nextIndex].onset - time);
      elements.nextTime.textContent = `${delta.toFixed(delta < 10 ? 2 : 1)} 秒`;
    } else {
      elements.nextTime.textContent = "—";
    }

    if (state.followPlayback && !elements.audio.paused && !state.userSeeking) followPlayhead(time);
  }

  function followPlayhead(time) {
    const desired = CANVAS_PADDING + time * state.pixelsPerSecond - elements.tabScroller.clientWidth * 0.34;
    const maxScroll = Math.max(0, elements.tabScroller.scrollWidth - elements.tabScroller.clientWidth);
    elements.tabScroller.scrollLeft = clamp(desired, 0, maxScroll);
  }

  function animationLoop() {
    updatePlaybackUI();
    if (!elements.audio.paused && !elements.audio.ended) {
      state.rafId = window.requestAnimationFrame(animationLoop);
    }
  }

  function syncPlayState() {
    const isPlaying = !elements.audio.paused && !elements.audio.ended;
    elements.playButton.classList.toggle("playing", isPlaying);
    elements.playButton.setAttribute("aria-label", isPlaying ? "暫停" : "播放");
    cancelAnimationFrame(state.rafId);
    if (isPlaying) state.rafId = window.requestAnimationFrame(animationLoop);
    else updatePlaybackUI();
  }

  function seekTo(seconds) {
    const duration = getDuration();
    const target = clamp(safeNumber(seconds), 0, duration || safeNumber(seconds));
    if (state.audioUrl) elements.audio.currentTime = target;
    else showToast("先載入對應音檔，才能從譜面跳轉播放。", true);
    updatePlaybackUI(true);
  }

  function updateFollowButton() {
    elements.followButton.setAttribute("aria-pressed", String(state.followPlayback));
  }

  async function togglePlayback() {
    if (!state.audioUrl) {
      showToast("請先載入對應的 MP3 或 WAV 音檔。", true);
      return;
    }
    if (elements.audio.paused) {
      try {
        await elements.audio.play();
      } catch (error) {
        showToast(`無法播放音檔：${error.message}`, true);
      }
    } else {
      elements.audio.pause();
    }
  }

  async function loadJsonFile(file) {
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text());
      const normalized = normalizePayload(payload);
      state.groups = normalized.groups;
      state.metadata = normalized;
      state.jsonDuration = normalized.duration;
      state.capo = normalized.capo;
      state.activeIndex = -1;
      state.nextIndex = -1;

      elements.capoRange.value = String(state.capo);
      elements.capoReadout.textContent = String(state.capo);

      elements.jsonFileName.textContent = file.name;
      elements.jsonState.textContent = `${normalized.groups.length} 個時間點`;
      elements.jsonDropZone.classList.add("loaded");
      elements.scoreTitle.textContent = normalized.title || basename(file.name);
      const sourceDetail = normalized.onsetCandidateCount
        ? `${normalized.onsetCandidateCount} 個起音候選，${normalized.decodedTimeCount} 個有 TAB`
        : (normalized.rawEventCount === normalized.groups.length
          ? `${normalized.groups.length} 個事件`
          : `${normalized.rawEventCount} 個事件，合併為 ${normalized.groups.length} 個時間點`);
      elements.scoreMeta.textContent = `${normalized.format} · ${sourceDetail} · ${formatClock(normalized.duration)} 音訊長度`;
      const coverage = normalized.diagnostics
        ? Number(normalized.diagnostics.decoded_onset_coverage)
        : Number.NaN;
      if (Number.isFinite(coverage) && coverage < 0.25) {
        elements.modelAlert.hidden = false;
        elements.modelAlert.textContent = `模型只在 ${(coverage * 100).toFixed(1)}% 的起音候選產生可解碼 TAB。灰色菱形是已偵測但沒有可靠指位的起音；這是推論輸出不足，不是播放器時間偏移。`;
      } else if (normalized.diagnostics && normalized.diagnostics.dropped_note_assignments > 0) {
        elements.modelAlert.hidden = false;
        elements.modelAlert.textContent = `指法最佳化時有 ${normalized.diagnostics.dropped_note_assignments} 個 MIDI 音符無法配置到可彈指板；可在 JSON diagnostics 查看原因。`;
      } else {
        elements.modelAlert.hidden = true;
        elements.modelAlert.textContent = "";
      }
      elements.tabEmpty.hidden = true;
      elements.tabCanvas.hidden = false;
      renderScore();
      setGlobalStatus();
      showToast(`已載入 ${file.name}`);
    } catch (error) {
      showToast(error instanceof SyntaxError ? "JSON 格式無法解析，請檢查檔案內容。" : error.message, true);
      elements.jsonInput.value = "";
    }
  }

  function loadAudioFile(file) {
    if (!file) return;
    if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
    state.audioUrl = URL.createObjectURL(file);
    state.audioDuration = 0;
    elements.audio.src = state.audioUrl;
    elements.audio.load();
    elements.audioFileName.textContent = file.name;
    elements.audioState.textContent = "讀取中";
    elements.audioDropZone.classList.add("loaded");
    elements.playButton.disabled = false;
    elements.muteButton.disabled = false;
    elements.seekRange.disabled = false;
    setGlobalStatus();
  }

  function setCapo(value) {
    state.capo = clamp(Math.round(safeNumber(value)), 0, 12);
    elements.capoRange.value = String(state.capo);
    elements.capoReadout.textContent = String(state.capo);
    if (state.groups.length) renderScore();
  }

  function setupDropZone(zone, type, handler) {
    ["dragenter", "dragover"].forEach((eventName) => {
      zone.addEventListener(eventName, (event) => {
        event.preventDefault();
        zone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      zone.addEventListener(eventName, (event) => {
        event.preventDefault();
        zone.classList.remove("dragover");
      });
    });
    zone.addEventListener("drop", (event) => {
      const file = [...event.dataTransfer.files].find((candidate) => type === "json"
        ? candidate.name.toLowerCase().endsWith(".json")
        : candidate.type.startsWith("audio/") || /\.(mp3|wav|m4a|flac|ogg)$/i.test(candidate.name));
      if (file) handler(file);
      else showToast(type === "json" ? "請拖入 .json 檔案。" : "請拖入可播放的音檔。", true);
    });
  }

  function bindElements() {
    [
      "audio", "audioDropZone", "audioFileName", "audioInput", "audioState", "capoAlert",
      "capoDown", "capoRange", "capoReadout", "capoUp", "currentNotes", "currentTime",
      "durationTime", "eventLayer", "followButton", "globalStatus", "jsonDropZone",
      "jsonFileName", "jsonInput", "jsonState", "muteButton", "nextTime", "nowTime",
      "modelAlert", "playButton", "playhead", "scoreMeta", "scoreTitle", "seekRange", "speedSelect",
      "statusDot", "tabCanvas", "tabEmpty", "tabScroller", "timeRuler", "toast", "zoomRange",
    ].forEach((id) => {
      elements[id] = document.getElementById(id);
    });
  }

  function bindEvents() {
    elements.jsonInput.addEventListener("change", () => loadJsonFile(elements.jsonInput.files[0]));
    elements.audioInput.addEventListener("change", () => loadAudioFile(elements.audioInput.files[0]));
    setupDropZone(elements.jsonDropZone, "json", loadJsonFile);
    setupDropZone(elements.audioDropZone, "audio", loadAudioFile);

    elements.capoRange.addEventListener("input", () => setCapo(elements.capoRange.value));
    elements.capoDown.addEventListener("click", () => setCapo(state.capo - 1));
    elements.capoUp.addEventListener("click", () => setCapo(state.capo + 1));
    elements.zoomRange.addEventListener("input", () => {
      const time = getCurrentTime();
      state.pixelsPerSecond = safeNumber(elements.zoomRange.value, 68);
      if (state.groups.length) {
        renderScore();
        followPlayhead(time);
      }
    });

    elements.followButton.addEventListener("click", () => {
      state.followPlayback = !state.followPlayback;
      updateFollowButton();
      if (state.followPlayback) followPlayhead(getCurrentTime());
    });
    elements.tabScroller.addEventListener("wheel", (event) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      event.preventDefault();
      state.followPlayback = false;
      updateFollowButton();
      elements.tabScroller.scrollLeft += event.deltaY;
    }, { passive: false });
    elements.tabScroller.addEventListener("pointerdown", () => {
      state.followPlayback = false;
      updateFollowButton();
    });
    elements.tabCanvas.addEventListener("click", (event) => {
      if (event.target.closest(".tab-event")) return;
      const rect = elements.tabCanvas.getBoundingClientRect();
      const time = (event.clientX - rect.left - CANVAS_PADDING) / state.pixelsPerSecond;
      seekTo(time);
    });

    elements.playButton.addEventListener("click", togglePlayback);
    elements.audio.addEventListener("play", syncPlayState);
    elements.audio.addEventListener("pause", syncPlayState);
    elements.audio.addEventListener("ended", syncPlayState);
    elements.audio.addEventListener("timeupdate", () => {
      if (elements.audio.paused) updatePlaybackUI();
    });
    elements.audio.addEventListener("loadedmetadata", () => {
      state.audioDuration = Number.isFinite(elements.audio.duration) ? elements.audio.duration : 0;
      elements.audioState.textContent = formatClock(state.audioDuration);
      elements.durationTime.textContent = formatClock(state.audioDuration);
      if (state.groups.length) renderScore();
      showToast(`音檔已就緒，長度 ${formatClock(state.audioDuration)}`);
    });
    elements.audio.addEventListener("error", () => {
      elements.audioState.textContent = "無法解碼";
      showToast("瀏覽器無法解碼這個音檔，請改用 MP3 或 WAV。", true);
    });

    elements.seekRange.addEventListener("pointerdown", () => { state.userSeeking = true; });
    elements.seekRange.addEventListener("input", () => {
      const previewTime = safeNumber(elements.seekRange.value);
      elements.currentTime.textContent = formatClock(previewTime);
      elements.nowTime.textContent = formatClock(previewTime, true);
      elements.playhead.style.left = `${CANVAS_PADDING + previewTime * state.pixelsPerSecond}px`;
    });
    elements.seekRange.addEventListener("change", () => {
      state.userSeeking = false;
      seekTo(elements.seekRange.value);
    });
    elements.speedSelect.addEventListener("change", () => {
      elements.audio.playbackRate = safeNumber(elements.speedSelect.value, 1);
    });
    elements.muteButton.addEventListener("click", () => {
      elements.audio.muted = !elements.audio.muted;
      elements.muteButton.classList.toggle("muted", elements.audio.muted);
      elements.muteButton.setAttribute("aria-label", elements.audio.muted ? "取消靜音" : "靜音");
    });

    document.addEventListener("keydown", (event) => {
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLSelectElement) return;
      if (event.code === "Space") {
        event.preventDefault();
        togglePlayback();
      } else if (event.code === "ArrowLeft" && state.audioUrl) {
        event.preventDefault();
        seekTo(getCurrentTime() - 5);
      } else if (event.code === "ArrowRight" && state.audioUrl) {
        event.preventDefault();
        seekTo(getCurrentTime() + 5);
      }
    });

    window.addEventListener("beforeunload", () => {
      if (state.audioUrl) URL.revokeObjectURL(state.audioUrl);
    });
  }

  function init() {
    bindElements();
    bindEvents();
    setGlobalStatus();
    updateFollowButton();
  }

  const globalScope = typeof window === "undefined" ? globalThis : window;
  globalScope.FretlineCore = {
    adjustedFret,
    basename,
    findActiveIndex,
    findPreviousIndex,
    formatClock,
    normalizePayload,
  };
  if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", init);
})();
