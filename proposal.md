# FretFlow 2-in-1 音樂分軌與吉他 TAB 平台提案

## 1. 文件目的

本文件是下一個開發 session 的實作依據。目標是把現有的 MVSep Mega 分軌、
Basic Pitch 音訊轉 MIDI／TAB，以及 Fretline 播放器整合成一個具有音樂庫的 Web
應用，並在本地完成驗證後部署到 AWS GPU 環境。

實作者應依照本文件的資料模型、API、頁面、測試與里程碑順序工作。如果遇到與本
文件衝突或未定義、且會改變資料模型或使用者流程的問題，先詢問使用者，不自行擴大
功能範圍。

## 2. 產品目標

FretFlow 提供彼此獨立但可串接的兩項功能：

1. **音樂分軌（Stem Separation）**
   - 使用者上傳音訊。
   - 選擇想要的 MVSep 音軌類別。
   - 系統保存原始音訊和完成分離的 stems 到個人音樂庫。
2. **吉他轉 TAB（Guitar to TAB）**
   - 使用者從音樂庫選擇 `acoustic-guitar` 或 `electric-guitar` stem。
   - 系統執行 Basic Pitch、MIDI 產生與吉他指板最佳化。
   - 完成的 TAB 進入獨立 TAB 樂譜庫，並可使用現有播放器開啟。

兩個功能可以分開使用，也可以在建立分軌工作時勾選「完成後自動產生吉他 TAB」，
形成一次完成的 2-in-1 流程。

## 3. 已確認的現況

- `infer_mvsep_mega.py` 已能使用 MVSep Mega v1.0.21 分離指定 stems。
- 模型 checkpoint 含 53 個獨立輸出 heads；現有程式會在完整、嚴格載入權重後，
  只保留使用者要求的 heads。
- `basic_pitch_tab.py` 已能將單一吉他音訊轉成 MIDI 與 TAB JSON。
- `sites/fretline/` 已有可播放原始音訊、MIDI 與 TAB 的 Vite 前端，但目前只能手動
  載入本機檔案，沒有 API、Job 狀態、音樂庫或登入。
- MVSep 真實 GPU 推論在 NVIDIA workstation 驗證；目前開發用 Mac 不負責 CUDA
  端到端推論。

## 4. MVSep 五軌選取規格

雖然 MVSep Mega v1.0.21 checkpoint 含 53 個輸出 heads，FretFlow 第一版只公開下列
五種產品需要的音軌，不在 UI 或 API 暴露其他模型 labels：

| UI 名稱 | MVSep stem label | 可轉 TAB |
|---|---|---|
| 木吉他 | `acoustic-guitar` | 是 |
| 電吉他 | `electric-guitar` | 是 |
| 貝斯 | `bass` | 否 |
| 鼓 | `drums` | 否 |
| 人聲 | `vocal` | 否 |

新增分軌頁以五個 checkbox 顯示。預設勾選木吉他與電吉他，使用者可增減選項；至少
選一軌，最多自然限制為這五軌。不提供「進階模式」、搜尋或自訂其他 48 個 labels。

後端以固定 allowlist 驗證輸入，不信任前端傳入的 stem name。模型仍會先嚴格載入
完整 checkpoint，再只保留被要求的 heads，因此現有 checkpoint 相容性驗證不變。

### 4.1 TAB 適用範圍

第一版只有以下 stem 顯示「產生 TAB」按鈕：

- `acoustic-guitar`
- `electric-guitar`

其他弦樂器雖然可能可被 Basic Pitch 辨識，但現有指板演算法固定為六弦吉他，不應
在沒有專用 tuning／指板模型時宣稱能產生正確 TAB。

## 5. 核心使用者流程

### 5.1 分軌功能

```text
進入「新增分軌」
→ 選擇或拖入音訊
→ 填寫曲名（預設取檔名）
→ 從木吉他、電吉他、貝斯、鼓、人聲選擇至少一軌
→ 可選「完成後自動產生吉他 TAB」
→ 上傳
→ 建立 Separation Job
→ 顯示排隊／處理進度
→ 完成後進入歌曲詳細頁
```

歌曲詳細頁列出每個 stem，提供：

- 播放／暫停與時間軸
- stem 名稱、時長、格式、完成狀態
- 下載
- 吉他 stem 的「產生 TAB」或「開啟 TAB」按鈕
- 失敗 stem 的錯誤摘要與重試

### 5.2 從既有 stem 產生 TAB

```text
音樂庫
→ 歌曲詳細頁
→ 選擇 acoustic-guitar 或 electric-guitar stem
→ 點擊「產生 TAB」
→ 設定 tuning、capo、max fret 與進階參數
→ 建立 Tab Job
→ 完成後開啟 TAB 詳細頁／播放器
```

### 5.3 獨立 TAB 樂譜庫

```text
TAB 樂譜庫
→ 依歌曲、吉他類型、tuning 或狀態篩選
→ 選擇一份 TAB
→ 載入 stem 音訊、MIDI 與 TAB JSON
→ 使用現有同步播放器練習
```

### 5.4 2-in-1 自動流程

若建立 Separation Job 時勾選自動 TAB：

1. 完成全部要求的 stems。
2. 對已選取且屬於可轉 TAB allowlist 的吉他 stems 建立 Tab Jobs。
3. 某一個 TAB 失敗不應讓成功的 stems 消失；歌曲標示為「分軌完成、部分 TAB
   失敗」。
4. 每一份 TAB 可獨立重試，且不得重新執行 MVSep。

## 6. Web 資訊架構

第一版保留現有 Vite／vanilla JavaScript，不因本次功能重寫成其他框架。將現有大型
`main.js` 拆成可測試模組。

### 6.1 主導覽

- **音樂庫**：所有歌曲及分軌狀態
- **新增分軌**：上傳與 stems 選擇
- **TAB 樂譜庫**：所有已建立或處理中的 TAB

### 6.2 路由

第一版使用 hash router，避免本地靜態 server 與 CloudFront SPA fallback 差異：

```text
#/library
#/separate
#/songs/:songId
#/tabs
#/tabs/:tabId
```

### 6.3 頁面定義

#### 音樂庫 `#/library`

- 搜尋曲名
- 狀態篩選：上傳中、分軌中、已完成、部分失敗、失敗
- Song card 顯示封面 placeholder、曲名、時長、建立時間、stem 數與 TAB 數
- 點擊進入歌曲詳細頁

#### 新增分軌 `#/separate`

- 單一音訊選擇與上傳進度
- 曲名
- 木吉他、電吉他、貝斯、鼓、人聲五個固定 checkbox
- 至少選一軌的驗證提示
- 自動轉 TAB toggle
- submit 後導向歌曲詳細頁

#### 歌曲詳細頁 `#/songs/:songId`

- 原始音訊 player
- Separation Job 狀態與階段
- stems 清單與各自播放器
- 木吉他／電吉他 stems 的 TAB action
- 刪除歌曲與產物（需要二次確認）

#### TAB 樂譜庫 `#/tabs`

- TAB cards：曲名、來源 stem、tuning、capo、狀態、事件數
- 搜尋與狀態篩選
- 點擊進入 TAB 詳細頁

#### TAB 詳細頁 `#/tabs/:tabId`

- 沿用現有 Fretline 播放器能力
- 自動載入 API 回傳的 TAB JSON、MIDI 和對應 stem 音訊
- Audio、MIDI、疊加、速度、循環、offset、capo 與自動跟隨
- 不再要求使用者手動選三個檔案
- 保留「本機手動載入」作為開發／除錯功能，但置於次要區域

## 7. Domain Model

所有 ID 使用 UUID。雲端模式的每筆資料都必須有 `owner_id`；本地模式使用固定
`local-user`，讓本地與雲端使用相同介面。

### 7.1 Song

```json
{
  "song_id": "uuid",
  "owner_id": "user-id",
  "title": "Song title",
  "source_filename": "source.mp3",
  "source_artifact_key": "songs/{song_id}/source/source.mp3",
  "duration_seconds": 240.1,
  "media_type": "audio/mpeg",
  "sha256": "...",
  "status": "READY",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601"
}
```

### 7.2 SeparationJob

主要欄位：

- `job_id`, `song_id`, `owner_id`
- `requested_stems`
- `auto_tab_stems`
- `status`, `stage`, `progress_percent`
- `model_version`, `container_digest`
- `started_at`, `finished_at`, `elapsed_seconds`
- `error_code`, `error_message`
- MVSep runtime、chunk、precision、RTF 與 peak VRAM diagnostics

### 7.3 Stem

主要欄位：

- `stem_id`, `song_id`, `separation_job_id`, `owner_id`
- `stem_type`
- `artifact_key`, `sample_rate`, `channels`, `frames`, `subtype`
- `duration_seconds`, `peak`, `status`
- `tab_eligible`

同一 Song、同一 Separation Job、同一 `stem_type` 只能有一份成功產物。

### 7.4 TabJob／Tab

主要欄位：

- `tab_id`, `job_id`, `song_id`, `stem_id`, `owner_id`
- `status`, `stage`, `progress_percent`
- `tuning`, `capo`, `max_fret`, `max_stretch`
- Basic Pitch thresholds
- `midi_artifact_key`, `tab_artifact_key`, optional `model_output_artifact_key`
- diagnostics、事件數、被捨棄音符數、錯誤資訊與時間

相同 stem 與相同參數的重複請求應回傳既有成功 TAB，除非使用者明確要求重新產生。

## 8. Artifact 目錄與雲端 Key

本地 filesystem 與 S3 使用相同相對 key：

```text
songs/{song_id}/
├── source/source.mp3
├── separations/{separation_job_id}/
│   ├── stems/acoustic-guitar.wav
│   ├── stems/electric-guitar.wav
│   ├── stems/bass.wav
│   ├── stems/drums.wav
│   ├── stems/vocal.wav
│   └── manifest.json
└── tabs/{tab_id}/
    ├── transcription.mid
    ├── transcription.tab.json
    ├── model-output.npz          # optional
    └── manifest.json
```

資料庫與 manifest 僅保存 artifact key，不保存本機絕對路徑或永久公開 URL。API 在
需要播放／下載時才產生短效 URL。本地模式將 key 轉成受控的 API file route。

## 9. Pipeline 程式設計

### 9.1 預計新增的 Python package

```text
fretflow/
├── __init__.py
├── domain.py                 # enums、dataclasses、驗證
├── config.py                 # 環境與限制
├── artifacts.py              # Local/S3 artifact store protocol
├── database.py               # SQLAlchemy engine/session 與 Alembic wiring
├── repository.py             # PostgreSQL repository protocol/implementation
├── progress.py               # stage/progress events
├── pipeline.py               # orchestration
├── worker.py                 # local/AWS Batch entrypoint
├── api.py                    # FastAPI app
└── services/
    ├── mvsep.py              # MVSep adapter
    └── tab.py                # Basic Pitch/TAB adapter
```

現有 `infer_mvsep_mega.py`、`basic_pitch_tab.py` 先保留 CLI，改成薄 wrapper 呼叫新的
services，避免兩份推論邏輯逐漸分岔。

### 9.2 核心介面

```python
class ArtifactStore(Protocol):
    def put_file(...): ...
    def materialize(...): ...
    def exists(...): ...

class JobRepository(Protocol):
    def create_song(...): ...
    def update_job(...): ...
    def list_stems(...): ...

class StemSeparator(Protocol):
    def separate(input_path, stems, output_dir, progress): ...

class TabTranscriber(Protocol):
    def transcribe(stem_path, options, output_dir, progress): ...
```

實際名稱可以因 Python typing 調整，但 service boundary 與 dependency injection 必須
保留，才能在 unit tests 使用 fake／mock，而不載入 GPU 模型。

### 9.3 冪等與恢復

- 每個 stage 先檢查資料庫狀態與已完成 artifact。
- 寫檔使用 `.part` 後 atomic rename。
- manifest 在每個 stage 完成後更新。
- 已成功分軌、但 TAB 失敗時只重跑 Tab Job。
- Job 重試不得重複建立相同 Stem／Tab records。
- `--overwrite` 只供管理／開發 CLI 使用，Web API 不直接暴露危險覆寫。

### 9.4 離線 Fixture Mode

本地 Mac 與一般 CI 不載入 MVSep checkpoint，也不要求 CUDA。設定
`INFERENCE_MODE=fixture` 時，`StemSeparator` 與 `TabTranscriber` 使用既有推論產物
模擬成功、失敗與部分完成流程：

- `downloads/by-gummy-b-stripped_bs_roformer_53_stems_mt_162_electric-guitar.mp3`
  作為現有 electric-guitar stem 範例。
- `basic_pitch_output/*.mid`、`*.tab.json`、`*.npz` 作為既有轉錄產物。
- `sites/fretline/public/assets/demo.mp3`、`demo.mid`、`demo.tab.json` 作為播放器 fixture。

`downloads/`、`basic_pitch_output/` 目前屬於 git-ignored 本地資料，測試不得假設每台
機器一定存在這些檔案。建立 `FRETFLOW_FIXTURE_DIR` 設定：若指定現有產物目錄就使用
真實離線產物；CI 則使用 `tests/fixtures/` 內小型、可提交且授權允許的合成 fixtures。
Unit tests 仍應以 fake objects 為主，離線音檔用於 integration／UI flow tests。

## 10. Local API Contract

本地和 AWS 使用相同 HTTP contract。第一版採 REST + polling，不加入 WebSocket。

### Songs／Upload

```text
POST   /api/songs
POST   /api/songs/{songId}/upload
POST   /api/songs/{songId}/upload-complete
GET    /api/songs
GET    /api/songs/{songId}
DELETE /api/songs/{songId}
```

雲端 `POST /api/songs` 回傳 presigned upload 資訊；本地 `/upload` 接受 multipart。
`upload-complete` 驗證 object 存在、大小、checksum 與可解碼性後才允許建立 Job。

### Separation

```text
GET  /api/stem-types
POST /api/songs/{songId}/separations
GET  /api/separations/{jobId}
POST /api/separations/{jobId}/retry
```

### Stems／Tabs

```text
GET  /api/songs/{songId}/stems
POST /api/stems/{stemId}/tabs
GET  /api/tabs
GET  /api/tabs/{tabId}
POST /api/tabs/{tabId}/retry
```

API 回應需有穩定 error shape：

```json
{
  "error": {
    "code": "UNSUPPORTED_STEM",
    "message": "此音軌類別不在 FretFlow 支援清單中",
    "details": {}
  }
}
```

## 11. Web 程式拆分

```text
sites/fretline/src/
├── main.js
├── api.js
├── router.js
├── state.js
├── components/
│   ├── audio-player.js
│   ├── job-progress.js
│   ├── stem-selector.js
│   └── stem-card.js
├── pages/
│   ├── library-page.js
│   ├── separate-page.js
│   ├── song-page.js
│   ├── tabs-page.js
│   └── tab-detail-page.js
└── player/
    ├── tab-normalizer.js
    ├── midi-engine.js
    └── tab-renderer.js
```

DOM rendering、資料 normalize、route parse、API mapping 與播放器時間計算不得全部留在
`main.js`；每個模組應有單一職責及可測試的純函式邊界。

## 12. 本地 Docker 開發環境

本地開發以 Docker Compose 啟動兩個必要 services：

```text
db   → 官方 PostgreSQL image
app  → FretFlow 主 Python image（FastAPI + Web build + 離線 Job runner）
```

資料庫不可和應用程式包進同一個 image。`db` 是有持久 volume 的獨立 container；
`app` 是無狀態、可重建並可推送 ECR 的 image。這樣本地 PostgreSQL 可直接對應 AWS
RDS for PostgreSQL，而不會把資料藏在應用 container filesystem。

### 12.1 預計新增檔案

```text
Dockerfile
compose.yaml
.dockerignore
.env.example
docker/
└── entrypoint.sh
alembic.ini
alembic/
├── env.py
└── versions/
```

### 12.2 `db` service

- 使用有明確版本 pin 的官方 `postgres:16-alpine` image；實作時再鎖定可用 minor
  version／digest，不使用浮動 `latest`。
- 僅對本機 loopback 開放 development port。
- 使用 named volume `postgres-data`。
- 設定 `pg_isready` health check。
- 帳密只放 `.env`，repository 僅提交不含秘密的 `.env.example`。

### 12.3 `app` service

`Dockerfile` 使用 multi-stage build：

1. `web-build`：從 Node image 安裝 lockfile dependencies 並建置 Vite。
2. `python-base`：從 `python:3.10-slim` 安裝 FFmpeg 與 Python dependencies。
3. `app`：複製 Python 程式與 Web `dist`，由 FastAPI 同時提供 API 和 SPA static
   assets。
4. `gpu-worker`：改以相容的 NVIDIA CUDA/PyTorch base 為基底，加入 MSST、模型
   runner 和相同的 FretFlow domain／repository code；release build 使用既有
   `download_mvsep_mega.py` 下載並驗證官方 config/checkpoint，將模型放在獨立、可快取
   layer，只推送到 private ECR。正式 build 前需確認模型授權允許此種私人部署。

`app` 和 `gpu-worker` 是同一個 Dockerfile 的兩個 targets，而不是把大型 CUDA runtime
放進日常 API image。它們以同一 Git commit 和 image label 追蹤版本。

### 12.4 本地啟動與測試命令

```bash
docker compose pull db
docker compose build --pull app
docker compose up --wait db app
docker compose exec app pytest
docker compose down
```

`app` 預設使用 `INFERENCE_MODE=fixture`，因此 Mac 可以不靠 GPU 完成上傳、音樂庫、
分軌 Job、轉 TAB Job 與播放器全流程。需要保留本地資料時不加 `-v`；只有使用者明確
要求清空資料時才執行 `docker compose down -v`。現有 `downloads/` 與
`basic_pitch_output/` 透過 read-only bind mount 提供給 fixture adapter，不複製進
`app` release image。

### 12.5 資料庫遷移

- 使用 SQLAlchemy + Alembic。
- Compose 啟動時先執行 `alembic upgrade head`，成功後再啟動 Uvicorn。
- AWS 上不允許多個 ECS replicas 同時自動 migration；部署時以一次性 ECS task 執行
  migration，成功後才更新 API service。
- 每個 migration 必須有 schema upgrade 測試，破壞性 migration 需另行確認。

### 12.6 可直接推送 AWS 的 Release Images

Mac 本地 Compose 使用 `app` target；release 時以 BuildKit 建立兩個 `linux/amd64`
artifacts：

```bash
docker buildx build --platform linux/amd64 --target app \
  -t "$APP_ECR_URI:$VERSION" --push .

docker buildx build --platform linux/amd64 --target gpu-worker \
  -t "$GPU_ECR_URI:$VERSION" --push .
```

推送前先執行 unit/integration tests、登入 ECR，並使用 immutable version tag。部署時
CDK 接受 image digest，不使用浮動 `latest`。`gpu-worker` 可以在 Mac 上完成 image
build，但 CUDA 推論只能在 NVIDIA workstation 或 AWS G6 驗證。

這裡所謂「整個 Docker image 打包丟到 AWS」是把可重建的應用與 worker images 推到
ECR；PostgreSQL data、使用者上傳音訊、模型輸出都不寫進 image，分別由 RDS 與 S3
持久化。

## 13. Unit Test 要求

使用者要求每個功能都有 unit test。實作時採以下最低標準：

### 13.1 Python

- 使用 `pytest`，保留既有 `unittest` 測試可執行性，逐步遷移而不一次重寫。
- 每個新增 public function、domain validation、service method 與 API handler 至少一個
  正常案例和一個相關失敗案例。
- GPU／模型 boundary 必須 mock；unit tests 不下載 checkpoint、不要求 CUDA。
- API 使用 FastAPI TestClient 與 fake repository／artifact store。
- PostgreSQL repository 使用 transaction rollback fixture；migration 在空資料庫與前一版
  schema 各測一次。
- Compose contract test 驗證 `db` health check 後 `app` 才可啟動。
- CDK 另以 assertions 測試資源、加密、IAM scope、Batch GPU requirement 與
  `minvCpus=0`。

預計測試檔：

```text
tests/
├── test_domain.py
├── test_config.py
├── test_artifacts.py
├── test_database.py
├── test_migrations.py
├── test_repository.py
├── test_mvsep_service.py
├── test_tab_service.py
├── test_fixture_inference.py
├── test_pipeline.py
├── test_worker.py
├── test_api_songs.py
├── test_api_separations.py
└── test_api_tabs.py
```

### 13.2 Web

- 使用 Vitest + jsdom。
- 每個 export function 和頁面狀態轉換都有 unit test。
- `fetch`、Audio、Web Audio、MIDI synthesizer 全部使用 test doubles。
- 至少覆蓋 upload、stem selection、job polling、library render、TAB 自動載入、API
  error 顯示與 route parsing。

```text
sites/fretline/src/**/*.test.js
```

### 13.3 整合與 E2E

Unit tests 之外仍需要：

- Mock model 的本地 pipeline integration test。
- `INFERENCE_MODE=fixture` 的完整 Docker Compose integration test。
- NVIDIA workstation 30 秒 smoke test。
- NVIDIA workstation 完整歌曲 smoke test。
- Playwright：上傳 fixture → 分軌完成 → 對木吉他／電吉他 stem 建 TAB → 開啟播放器。
- AWS：30 秒音訊 Batch smoke test，驗證 S3 artifacts、PostgreSQL 狀態與 logs。

Coverage gate：新 Python 與 JavaScript 程式碼 line coverage 90% 以上，重要 domain、
權限與狀態轉換 branch coverage 90% 以上。Coverage 不能取代逐項功能測試。

## 14. AWS 目標架構

此應用包含自訂 CUDA GPU Batch workload，不使用 Launch with AWS 的自動前端遷移
流程；基礎設施使用 AWS CDK 明確定義。

```text
CloudFront（global）
        │
        ▼
Application Load Balancer
        │
        ▼
ECS Fargate `app` service ────── RDS for PostgreSQL
        │                              │
        ├── presigned S3 upload        │
        ├── submit Batch Job           │
        └── serve built Web SPA        │
                       │               │
                       ▼               │
                AWS Batch Queue        │
                       ▼               │
               EC2 G6 / NVIDIA L4      │
               `gpu-worker` image ─────┘
                       │
                       └── S3 artifacts

Batch state events → EventBridge → SQS → app reconciliation worker
App + GPU worker images → private ECR repositories
DB credentials → Secrets Manager
Logs/metrics → CloudWatch
App login → Cognito managed login
```

API 和 Web 使用同一個 `app` image 部署到 ECS Fargate；GPU 推論使用同一 repository、
同一 Dockerfile 建置出的 `gpu-worker` target，部署到 AWS Batch。資料庫使用 RDS for
PostgreSQL，不把本地 PostgreSQL container 推到 AWS。這保留標準 PostgreSQL 相容性、
資料持久化與本地開發一致性，也避免將 stateful DB 綁在可隨時替換的 application task。

### 14.1 新 AWS experience 限制

部署前必須先完成 Gate 0：

1. 使用者到 **AWS Settings → View all projects → Overview → Additional Info →
   Region** 確認 project 的 selected Region；若可從 `~/.aws/config` 明確確認，也可
   使用該值。
2. 所有 Regional resources（ECS、ALB、RDS、S3、Cognito、Batch、ECR、EventBridge、
   SQS、CloudWatch、Secrets Manager）只建立在 selected Region。
3. 不建立 cross-Region replication、StackSets、Lambda@Edge 或跨區 Route 53 routing。
4. 確認 project 已升級至 paid plan、spend limit 足夠，且 selected Region 支援
   AWS Batch 與 G6。
5. 若服務建立失敗，先執行 `aws freetier get-account-plan-state`，再依 FREE／PAID
   supported services 清單判斷；需要時由使用者啟用 advanced AWS services。

若 project 的固定 selected Region 沒有 G6／AWS Batch，不能違反 project 規則改到
其他 Region；應先停在部署 Gate，請使用者調整 AWS project／advanced features。

### 14.2 App、GPU 與 Image 部署

- `app` target 推送到 private ECR repository，ECS Fargate 執行 FastAPI 與 build 後的
  Web SPA；Fargate task 不要求 GPU。
- `gpu-worker` target 推送到另一個 private ECR repository／immutable tag，AWS Batch
  在 G6 執行；Fargate 不承擔 GPU 工作。
- ECR image tags 不覆寫，以 Git commit SHA 或 release version 標記，部署時 pin image
  digest。
- ECR 啟用 registry scanning 與 lifecycle policy，保留近期可回滾版本並清理舊的
  untagged images。
- ECS execution role 僅負責 pull image、logs 和讀取 Secrets Manager；app task role
  只授予需要的 S3、Batch、SQS 與狀態操作。
- API image 不包含 CUDA checkpoint，避免每次更新 Web/API 都重新傳送大型 GPU
  layers。

### 14.3 GPU 與 Batch

- 第一版使用 `g6.2xlarge`、單張 L4、每 Job 一張 GPU。
- AWS Batch managed EC2 compute environment。
- `minvCpus=0`；第一版 `maxvCpus` 只允許一台 GPU instance 的容量。
- 先使用 On-Demand；確認冪等、重試與成本後才加入 Spot。
- Job definition 明確要求 `GPU=1`。
- durable data 一律放 S3；instance disk 只作 scratch。

### 14.4 PostgreSQL

- 本地使用官方 PostgreSQL container；AWS 使用 private-subnet RDS for PostgreSQL。
- RDS 與 local DB 使用相同 Alembic migrations。
- ECS app 和 Batch worker 透過 security groups 存取 DB，不開放 public access。
- DB credentials 放 Secrets Manager，不寫入 image、task definition 明文或 repository。
- 開發第一版使用單一小型 RDS instance；RDS 不會像 Batch 一樣 scale to zero，因此
  在 AWS 成本估算與 spend limit 中單獨列出固定資料庫成本。
- 部署前由一次性 ECS migration task 更新 schema，之後才滾動更新 app service。

### 14.5 儲存與隱私

- S3 Block Public Access 全開、server-side encryption、TLS only。
- 使用 owner-scoped keys 與短效 signed URLs。
- 上傳使用 UUID key，不能由原始檔名決定 object key。
- 未完成 multipart uploads 與 failed-job scratch 設 lifecycle cleanup。
- 第一版完成的歌曲、stems 與 TAB 保留至使用者刪除，以符合「音樂庫」語意。
- 刪除 Song 時 cascade 刪除其 DB records 與 S3 artifacts；先做二次確認。

### 14.6 App 使用者登入

第一版雲端預設使用 Cognito managed login，音樂庫以登入者 subject 隔離。本地開發
使用固定 `local-user`。若使用者決定只部署成單人私人站，可在開始 AWS auth 實作前
簡化，但不得讓 S3 或 API 直接公開。

## 15. 基礎設施程式碼

新增 `infra/` TypeScript CDK app：

```text
infra/
├── bin/fretflow.ts
├── lib/network-stack.ts
├── lib/data-stack.ts
├── lib/app-stack.ts
├── lib/compute-stack.ts
├── lib/edge-stack.ts
├── test/*.test.ts
├── cdk.json
├── package.json
└── package-lock.json
```

部署流程固定為：

```text
npm test
npx cdk synth --strict
npx cdk diff
npx cdk deploy
```

第一次部署才執行 selected Region 的 `cdk bootstrap`。Production deploy 不使用
`--hotswap`、`--hotswap-fallback` 或 `--express`。

## 16. 實作順序

### Milestone 0：決策與環境確認

- 確認 help level。
- 確認 selected Region、AWS paid plan、spend limit 與 G6/Batch 可用性。
- 確認第一版使用 Cognito 個人音樂庫。
- 確認 PostgreSQL 16、本地 Docker Compose 與五軌固定 allowlist。

完成條件：沒有會改變 domain model 的未決問題。

### Milestone 1：Docker Compose 與測試環境

- 新增 multi-stage Dockerfile、Compose、PostgreSQL health check 與 volumes。
- 建立 `app` target、fixture inference mode 和 `.env.example`。
- 加入 SQLAlchemy／Alembic 基礎與 Compose contract test。

完成條件：執行 `docker compose up --wait` 後可開啟 app health endpoint，且測試能在
container 內執行。

### Milestone 2：Domain 與測試骨架

- 建立 Python package、domain models、enums、config 與 tests。
- 定義 manifest schema 和 API error schema。
- 建立 Web Vitest 與基礎 router tests。

完成條件：純 domain／config tests 全部通過。

### Milestone 3：拆分兩個推論 service

- 將現有 MVSep 邏輯移至可注入 service。
- 將 Basic Pitch／TAB 邏輯移至可注入 service。
- 原 CLI 改為 wrapper 並保持相容。
- 補齊每個 public function 的 tests。

完成條件：既有測試與新 service tests 通過，CLI 行為不退化。

### Milestone 4：PostgreSQL Music Library 與 Job Pipeline

- LocalArtifactStore、PostgreSQL repository 與 Alembic migrations。
- Separation Job、Tab Job、2-in-1 orchestration。
- resume、retry、atomic writes、manifest。
- mock-model 與現有產物 fixture integration tests。

完成條件：無 GPU CI 能完整模擬兩條工作流程。

### Milestone 5：本地 API

- FastAPI endpoints、validation、polling status、local file serving。
- 完整 handler tests 和 contract tests。

完成條件：Web 所需 API contract 全部可在本地啟動與測試。

### Milestone 6：Web 2-in-1 UX

- 拆分現有播放器模組。
- 實作三個主頁籤和五個 routes。
- 實作上傳、stem selector、library、進度與 TAB 自動載入。
- Vitest unit tests 與 Playwright mocked E2E。

完成條件：使用 mock worker 可從上傳一路操作到 TAB 播放器。

### Milestone 7：GPU Workstation 驗證

- 30 秒音訊：五個允許 stems 分離與兩種 guitar TAB。
- 完整歌曲：2-in-1。
- 記錄 VRAM、RAM、RTF、模型載入時間與產物大小。
- 驗證同時輸出五軌是否適合 L4；若不足，worker 內分批執行，但 API allowlist 不變。

完成條件：真實模型輸出符合 manifest 與 Web API contract。

### Milestone 8：GPU Worker Image

- 建置同一 Dockerfile 的 `gpu-worker` target 與 preflight command。
- Python 3.10、CUDA/PyTorch、MSST、Basic Pitch TFLite、FFmpeg。
- Model checksum verification。
- Docker image unit tests、dependency check 與 NVIDIA smoke test。

完成條件：相同 `gpu-worker` image 能在 workstation 與目標 AWS GPU runtime 執行；
`app` image 仍可獨立更新，不重建 CUDA layers。

### Milestone 9：AWS CDK 與部署

- selected Region bootstrap。
- Network、Data、App、Compute、Edge stacks 與 CDK assertions。
- 將 `app` 與 `gpu-worker` images 以 immutable tags 推到 ECR。
- 建立 RDS PostgreSQL、執行一次性 migration task、部署 ECS Fargate app。
- 執行 Batch 30 秒 smoke test，並部署 Cognito／CloudFront。
- Browser E2E、CloudWatch 與成本確認。

完成條件：登入後可上傳、分軌、轉 TAB、重開音樂庫並播放既有結果；閒置時沒有
GPU instance 常駐。

## 17. Definition of Done

- 使用者可單獨使用分軌功能。
- 使用者可從音樂庫既有木吉他或電吉他 stem 單獨建立 TAB。
- 使用者可選擇 2-in-1 自動流程。
- 使用者可在獨立 TAB 樂譜庫重開過去結果。
- UI 只提供木吉他、電吉他、貝斯、鼓、人聲，後端以相同五軌 allowlist 驗證。
- 任一 TAB 失敗不破壞已成功 stems。
- 重試具有冪等性，不重跑不必要的昂貴階段。
- 每個新增功能及 public function 都有 unit test。
- GPU 外部依賴以 mock unit tests + 真實 smoke tests 分層驗證。
- Mac 可用 `INFERENCE_MODE=fixture` 和現有產物完成整個 Docker Compose 離線流程。
- Web、API、worker、CDK tests 全部通過。
- `app` 與 `gpu-worker` images 可重現建置並以 immutable digest 部署到 ECR。
- PostgreSQL schema 由 Alembic 管理，本地 Compose 與 AWS RDS 使用相同 migrations。
- 所有 AWS Regional resources 只存在 project selected Region。
- S3 非公開、使用者資料隔離、沒有長期 AWS credentials 寫入 repository。
- AWS Batch 閒置時縮到零。

## 18. 預設決策與開始前可覆寫項目

為了讓下一個 session 能直接開始，若使用者沒有另外指定，採用以下預設：

1. 雲端版使用 Cognito email login，每位使用者有私人音樂庫。
2. 分軌預設選 `acoustic-guitar` 與 `electric-guitar`。
3. 分軌 UI/API 只允許 `acoustic-guitar`、`electric-guitar`、`bass`、`drums`、
   `vocal`，不提供其他模型 heads。
4. 只有 `acoustic-guitar`、`electric-guitar` 可轉 TAB。
5. 完成的原音、stems、MIDI、TAB 保留至使用者刪除；失敗暫存自動清除。
6. 第一版使用 REST polling，不做 WebSocket。
7. 第一版保留 Vite／vanilla JavaScript，不進行前端框架重寫。
8. 本地使用 PostgreSQL 16 Docker container；AWS 使用 RDS for PostgreSQL。
9. 主 Dockerfile 提供 `app` 與 `gpu-worker` targets，分別部署 ECS Fargate 與 Batch。
10. 第一版 AWS 使用 On-Demand G6，不使用 Spot。

以下任一項若要改動，應在對應 Milestone 開始前詢問並更新本文件：登入模式、五軌
allowlist、資料保留政策、可轉 TAB 的樂器範圍、PostgreSQL engine、selected Region
限制與 Web framework。

