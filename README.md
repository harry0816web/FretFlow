# FretFlow

## 本地 Web 開發

FretFlow 的 API、打包後 Web 與 PostgreSQL 可用 Docker Compose 啟動；預設使用
`fixture` 推論模式，不需要 CUDA：

```sh
cp .env.example .env
docker compose build app
docker compose up --wait db app
curl http://127.0.0.1:8000/api/health
docker compose exec app pytest
docker compose down
```

`docker compose down` 會保留資料庫與 artifact volumes；除非確定要清空本地資料，
不要加 `-v`。未使用 Docker 時，也可執行 `uv run pytest` 跑 Python 測試，並在
`sites/fretline/` 執行 `npm test` 與 `npm run build`。

前端完整驗證包含 Vitest 與 mocked Playwright 2-in-1 流程。首次執行需安裝
Playwright Chromium：

```sh
cd sites/fretline
npm ci
npx playwright install chromium
npm run test:all
npm run build
```

下載單支 YouTube 影片並轉換成 MP3（需安裝 FFmpeg）：

```sh
uv run youtube_to_mp3.py "https://www.youtube.com/watch?v=uTUWCJjg1bc"
```

網址放在引號內時，`?`、`=`、`&` 不需要再加反斜線。腳本也會修正貼入的 `\?`、`\=`、`\&`，並拒絕首頁、頻道及純播放清單網址。

預設輸出至 `downloads/`，可用 `-o` 指定資料夾。只有確認本次下載產生或確認可用的非空 MP3 後，才會顯示成功及完整檔案路徑。

執行回歸測試：

```sh
uv run python -m unittest discover -s tests
```

## MVSep Mega 木吉他／電吉他分離

目前使用官方 MVSep Mega v1.0.21 BS-RoFormer checkpoint。模型原本有 53 個
輸出，本專案的推論器會先嚴格載入完整 checkpoint，再只保留
`acoustic-guitar` 與 `electric-guitar` 兩個獨立輸出 heads；共享 backbone 不變。
這會減少 VRAM、CPU RAM 與磁碟輸出，但不能把兩類再細分成不同吉他手。

### 1. Workstation 環境

已知 workstation 使用 RTX 5090、`torch 2.11.0+cu130`。MSST 0.1.0 官方支援
`torch >=2.0.1,<2.12`，因此保留現有 CUDA-enabled Torch，不需要降版或重裝。

先進入既有 conda 環境並確認 5090 可見：

```sh
conda activate /mnt/facesim/Chiikawa/conda-envs/final_4

python --version
python -c "import torch; print(torch.__version__, torch.version.cuda); print(torch.cuda.get_device_name(0)); print(torch.cuda.is_available())"
```

安裝分離所需的最小依賴。`--upgrade-strategy only-if-needed` 會沿用已符合條件的
`torch 2.11.0+cu130`：

```sh
python -m pip install --upgrade-strategy only-if-needed -r requirements-mvsep.txt
python -m pip check
python infer_mvsep_mega.py --check-env
```

不要安裝上游 repository 的完整訓練 requirements；其中包含 GUI、訓練器及其他
模型的依賴，本推論流程不需要。

### 2. 下載模型

將 `download_mvsep_mega.py` 複製到 GPU workstation 後，可直接用系統 Python
下載 MVSep Mega v1.0.21 的官方設定與 checkpoint，不需要先安裝專案依賴：

```sh
python3 download_mvsep_mega.py
```

預設下載到 `models/mvsep_mega/`。腳本會保留 `.part` 檔以支援中斷續傳，
完成後驗證官方檔案大小與 SHA-256。也可以指定其他位置：

```sh
python3 download_mvsep_mega.py --output-dir /data/models/mvsep_mega
```

若只想先測試小型設定檔下載：

```sh
python3 download_mvsep_mega.py --asset config
```

完整 checkpoint 約 1.28 GiB。腳本支援 `.part` 中斷續傳，完成後會核對官方
檔案大小與 SHA-256。

### 3. 執行推論

輸入 MP3、WAV 或 FLAC：

```sh
python infer_mvsep_mega.py downloads/Prophecy.mp3
```

也可以一次輸入多個檔案或整個資料夾；模型只載入一次：

```sh
python infer_mvsep_mega.py downloads/song-01.mp3 downloads/song-02.wav
python infer_mvsep_mega.py /mnt/NAS/Chiikawa/FretFlow/downloads
```

預設產物：

```text
mvsep_output/Prophecy/
├── acoustic-guitar.wav
├── electric-guitar.wav
└── manifest.json
```

WAV 預設為 44.1 kHz stereo float32，保留給後續 MIDI／TAB pipeline 使用。
`manifest.json` 記錄輸入與模型 hash、GPU／CUDA／PyTorch 版本、推論參數、耗時、
real-time factor、峰值 VRAM 以及輸出音訊資訊。

指定模型、輸出及 GPU 路徑：

```sh
python infer_mvsep_mega.py input.mp3 \
  --model-dir /mnt/NAS/Chiikawa/FretFlow/models/mvsep_mega \
  --output-dir /mnt/NAS/Chiikawa/FretFlow/mvsep_output \
  --device cuda:0
```

RTX 5090 先使用官方 20 秒 chunk、overlap 2 與 FP16。若發生 CUDA OOM，再依序
嘗試 10 秒、5 秒；縮短 chunk 會增加推論次數，結果也可能在 chunk 邊界有些差異：

```sh
python infer_mvsep_mega.py input.mp3 --chunk-seconds 10
python infer_mvsep_mega.py input.mp3 --chunk-seconds 5
```

其他常用參數：

```sh
# 已存在輸出時明確覆寫
python infer_mvsep_mega.py input.mp3 --overwrite

# 輸出較小的 24-bit PCM WAV
python infer_mvsep_mega.py input.mp3 --subtype PCM_24

# 下載腳本已驗證過模型，可信任目前檔案時可略過每次 1.28 GiB hash 計算
python infer_mvsep_mega.py input.mp3 --skip-checksum
```

第一次先跑 20–30 秒測試片段，確認 `manifest.json` 的峰值 VRAM 與 RTF，再跑整曲。
單首歌曲使用一張 GPU；若有多張 GPU，讓不同 job 分別使用 `cuda:0`、`cuda:1`
處理不同歌曲，比 batch size 1 的 DataParallel 更合適。

五軌與兩份 guitar TAB 的 Milestone 7 驗收步驟及已記錄的 RTX 5090 基準，請參閱
[`docs/gpu-validation.md`](docs/gpu-validation.md)。驗收工具 `validate_gpu_smoke.py`
會檢查 manifest、五軌輸出、GPU metrics 與兩份非空 TAB。

可以用 FFmpeg 建立不經有損重編碼的 30 秒 smoke-test WAV：

```sh
ffmpeg -ss 60 -t 30 -i downloads/Prophecy.mp3 \
  -ar 44100 -ac 2 -c:a pcm_f32le /tmp/prophecy-30s.wav

python infer_mvsep_mega.py /tmp/prophecy-30s.wav
```

## Basic Pitch 音訊轉 TAB

輸入 MVSep 分離後的電吉他或木吉他 MP3／WAV。程式先用 Spotify Basic Pitch 產生帶有 onset、offset、力度及 pitch bend 的 MIDI，再以全曲 Viterbi 搜尋把 MIDI pitch 配置成可彈的六弦 TAB：

```sh
uv run basic_pitch_tab.py \
  "downloads/by-gummy-b-stripped_bs_roformer_53_stems_mt_162_electric-guitar.mp3"
```

專案固定使用 Python 3.10，因為這是 Spotify 官方列出的 Apple Silicon 支援版本。macOS 會使用 Basic Pitch 隨套件提供的 Core ML 模型；它不是 PyTorch 模型，因此不經過 MPS。

預設產物位於 `basic_pitch_output/`：

- `*.mid`：Basic Pitch 的原始 MIDI 辨識結果，可先用 DAW 或 MuseScore 聽／看，獨立檢查音高和時間是否正確。
- `*.tab.json`：MIDI 經吉他指板最佳化後的結果，可直接載入本專案播放器。

指法器會保留盡可能多的同時發聲音符，限制一弦一音與和弦 fret span，並在整首歌上最小化手位移動；若 MIDI 和弦超過六音、超出所選指板，或無法形成可彈指法，會優先捨棄較弱的音並記錄在 JSON diagnostics。

常用參數：

```sh
# Drop D、24 格電吉他
uv run basic_pitch_tab.py input.mp3 --tuning drop-d --max-fret 24

# 錄音實際使用 capo 2；JSON 仍保存絕對 fret，播放器顯示相對 capo 格數
uv run basic_pitch_tab.py input.mp3 --capo 2

# 收緊 onset 可接受度，或調整 Basic Pitch 偵測門檻
uv run basic_pitch_tab.py input.mp3 \
  --onset-tolerance 0.035 \
  --onset-threshold 0.55 \
  --frame-threshold 0.35
```

## TAB 播放器

瀏覽器版播放器位於 [`tab-player/index.html`](tab-player/index.html)。它可以：

- 匯入 `*.tab.json` 與對應的 MP3 / WAV。
- 依音訊時間顯示目前與下一個 string / fret 事件。
- 使用 Basic Pitch 的 note onset 對齊播放器；JSON 同時保留 note offset 供後續節奏顯示使用。
- 選擇 0–12 格 capo，將原始絕對格數換算為相對 capo 格數。
- 點譜面跳轉、調整播放速度、縮放時間軸與自動跟隨播放。

以本機 HTTP server 開啟：

```sh
python3 -m http.server 4173 --directory tab-player
```

接著瀏覽 `http://localhost:4173/`。JSON 只記錄原音檔路徑，瀏覽器基於安全限制不能直接讀取該路徑，所以仍需手動選擇一次音檔。

## macOS MIDI 播放器

專案另附一個以 Swift 與 AVFoundation 製作的原生命令列播放器，可直接聆聽
`basic_pitch_output/*.mid`，用來獨立檢查 MIDI 轉換的音高與時間。它預設使用
與 Spotify demo 相同的 GeneralUser GS 音色庫（若本機已下載），否則使用
macOS 內建音色庫。預設為電鋼琴、關閉預測彎音；可加 `--pitch-bends` 對照。

```sh
cd midi-player
make build
make inspect MIDI="../basic_pitch_output/example.mid"
make run MIDI="../basic_pitch_output/example.mid"
```

播放時可輸入 `p` 暫停或繼續、`s 30` 跳至第 30 秒、`r 0.75` 改為 75%
速度、`l` 切換循環，以及 `q` 離開。更多選項請參閱
[`midi-player/README.md`](midi-player/README.md)。

## MIDI 去雜音與 TAB 條件最佳化

`refine_midi.py` 會另外輸出保守去雜音 MIDI、經吉他指位配置的 MIDI/TAB，
以及逐筆變更報告。指位搜尋會記住先前仍在發聲的弦，以減少不必要的延音切斷。
斷點合併需要同一音訊的模型訊號；沒有模型訊號時保留重複撥弦。

```sh
uv run refine_midi.py basic_pitch_output/example.mid \
  --output-dir basic_pitch_output/example-refined
```

研究依據、模型訊號保存、A/B 試聽與限制詳見
[`docs/midi-refinement.md`](docs/midi-refinement.md)。
