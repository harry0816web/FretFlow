@AGENTS.md

# FretFlow

音樂轉吉他譜（music to tab）服務：MVSep 音源分離 → Basic Pitch 轉 MIDI → 吉他 tab。Python（uv）+ PostgreSQL（alembic）+ Docker Compose 後端，前端在 `sites/fretline/`（Vitest + Playwright）。詳見 `README.md`。用繁體中文回答；實作前先列計畫。

- 本機：`docker compose up --wait db app`（預設 `fixture` 推論模式，不需 CUDA）；`uv run pytest`。
- 不要對 `docker compose down` 加 `-v`（會清空資料）。

## 近期方向（取自 Codex，2026-10-27）
- 已把 MVSep 與 music-to-tab 兩條 pipeline 串接，依 `proposal.md` 實作。
- ~~規劃部署到 AWS~~：2026-11-26 取消，改為只在本機執行。
- 本機用 `./fretflow.sh up` 自動偵測：NVIDIA → `gpu-worker` 容器（CUDA）；Apple Silicon → 原生 macOS worker（MPS，Docker 無法用 Metal）；其他 → `cpu-worker`。web/API/DB 一律在 Docker。
