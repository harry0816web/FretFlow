# FretFlow

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

## MVSep Mega 權重

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
# FretFlow
