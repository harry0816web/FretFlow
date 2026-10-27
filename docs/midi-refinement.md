# MIDI 去雜音與吉他條件最佳化

研究與本機驗證日期：2026-10-27。這是可調整、可追蹤的第一版後處理，
不是已用人工真值驗證的自動修譜系統。適用於一把吉他的分軌音訊。

## 官方 demo 與目前播放器

檢查 [Spotify demo](https://basicpitch.spotify.com/) 實際載入的
[頁面程式](https://basicpitch.spotify.com/_next/static/chunks/pages/index-5eb44d2184e903c2.js)，
可以確認它使用 FluidSynth、GeneralUser GS 1.471、program 4（Electric Piano 1），
並關閉 reverb。頁面送入播放的 MIDI 建構函式只加入音高、起始時間、長度與力度，
沒有加入 pitch-bend 事件；畫面可顯示彎音不等於播放路徑也使用了彎音。

本機播放器現在預設同一音色庫和 program，並關閉預測 pitch bends。
`--pitch-bends` 可恢復播放彎音，`--program 27` 可試 clean guitar。
每軌獨立 sampler，移除預覽中的 program/bank 切換，確保選定音色穩定。
音符資料原檔不會修改；AVFoundation 與 FluidSynth 的包絡和效果仍可能不同。

MIDI 沒有原音訊中的底噪：聽到的「雜音」可能是誤判音符、錯誤彎音，或合成音色本身。
改善音色無法消除錯誤音符；關閉彎音也會移除真實推弦、滑音和揉弦的表情。

## 實作流程

1. 讀取 MIDI，依 tuning/capo/fret 範圍刪除無法配置的音。
2. 預設只刪除同時短於 180 ms 且 amplitude < 0.40 的音。
   MIDI velocity / 127 在此是 Basic Pitch activation 的近似，並非校準過的正確率。
   快速強音與長弱音保留；短而弱的正常裝飾音仍可能誤刪，需 A/B 判斷。
3. 相同音高、間隔不超過 80 ms 的音，只有取得同一音訊模型 cache 才評估合併。
   要求間隙至少 80% 的 frame activation ≥ 0.20、第二音起點附近 onset < 0.25，
   且 frame rise < 0.08；否則保留為兩次撥弦。沒有證據就不合併。
4. 產生每個起音群的指位候選，限制同弦單音及該群按弦跨度，
   以寬度 64 的 beam search 同時考量手位移動與所有仍在延音的弦。
   重用仍在發聲的弦有高代價，優先尋找其他指位，避免不必要的切音。
5. 若選定指位仍需重用同一弦，將前音結尾截到下一次起音並逐筆記錄。
   回產 MIDI 使用每個音原本的起點，保留掃弦微小時間差。

所有操作寫入 report，包括刪音、合併及其證據、未合併候選、TAB 省略音、同弦切音。
輸出檔若已存在會拒絕覆寫，請換一個 `--output-dir`。

## 使用方式

從專案根目錄執行。既有 MIDI 可先清理，不需要重跑模型，但不會自動合併斷點：

```sh
uv run refine_midi.py basic_pitch_output/example.mid \
  --output-dir basic_pitch_output/example-refined
```

要使用起音／延音證據，轉錄時保存模型訊號。使用另一個輸出名稱可保留舊版：

```sh
uv run basic_pitch_tab.py "downloads/input.mp3" \
  -o basic_pitch_output/analysis.tab.json \
  --save-model-output basic_pitch_output/analysis.npz

uv run refine_midi.py basic_pitch_output/analysis.mid \
  --model-output basic_pitch_output/analysis.npz \
  --output-dir basic_pitch_output/analysis-refined
```

cache 儲存 Basic Pitch 校正過的 frame 時間軸，避免長曲在模型視窗接縫累積時間誤差。
會核對來源 TAB 的 MIDI 路徑及 cache 音訊來源。tuning、capo、max-fret 預設繼承來源 TAB，
也可明確指定；沒有來源 TAB 時使用標準調弦、capo 0、22 格。

輸出包括 `*.clean.mid`、`*.playable.mid`、`*.playable.tab.json`、`*.report.json`。
兩個新 MIDI 都是無彎音的電鋼琴診斷版本，保留絕對秒數，使用 120 BPM 時間座標；
不複製原 MIDI 的 tempo map、控制器、表情或多樂器配置。
先比較原始 MIDI 與 clean，再比較 clean 與 playable，能分辨去雜音和指位的影響。

## 這次樣本結果

電吉他分軌約 107 秒，192 notes，12 個音高分軌；原始 TAB 沒有刪掉任何音。
第一輪指位方法造成 6 處延音切短，加入跨事件延音記憶後降為 0。
最新結果位於 `basic_pitch_output/refined-final/`：

- 去除 20 個短弱候選，留下 172 notes；尚未經人工確認這 20 個全是雜音。
- 37 個同音短間隔候選，0 個符合安全合併條件，多數有明確起音或 activation 上升。
- TAB 保留全部 172 notes，沒有同弦延音切短。這個樣本 clean/playable 音符內容一致，
  指位主要改善 TAB 配置，不能宣稱額外提升 MIDI 音高準確率。

試聽最新結果：

```sh
make -C midi-player build
midi-player/.build/midi-player basic_pitch_output/refined-final/refinement-source.playable.mid

# 同音色播放原預測，預設也不使用彎音，公平比較刪音效果
midi-player/.build/midi-player basic_pitch_output/refinement-source.mid
```

## 音樂理論與吉他條件的下一層

Basic Pitch 原模型沒有「key、和弦、指位」輸入欄位；無須重訓就能做的是
在解碼／後處理加入條件。調性、和弦、節拍、旋律連續性適合作為軟性代價，
不能直接把調外音改掉，否則藍調音、借用和弦、經過音與推弦會受傷。
同理，八度或五度的弱音可能是泛音誤判，也可能是正常 power chord，
需要額外音訊證據才能決定，現在沒有自動刪除這類音。

目前指位搜尋仍是有限候選、有限 beam 的近似解，和弦跨度限制作用於起音群，
尚未完整檢查跨起音群的所有持續按弦、手指數、橫按、點弦與特殊技巧。
可彈不代表與原演奏相同；六弦單聲部假設也不適用於疊錄的多把吉他。

如要進一步改善真正的預測準確率，建議保留人工標註的短片段，分別比較
note precision/recall、onset/offset 偏差、重複撥弦保留率，以及同弦衝突數。
不要只以刪掉多少音或聽起來比較順作為成功標準。

## 研究依據

- [Basic Pitch 原始碼](https://github.com/spotify/basic-pitch/blob/main/basic_pitch/note_creation.py)：
  onset/frame 門檻、minimum note length、頻率範圍、pitch-bend 解碼。
  提高 onset 門檻可能減少過度切音，但也會漏掉真實起音；提高 frame 門檻
  可能去除弱音卻讓尾音更短，因此不能單純把所有門檻一起調高。
- [ICASSP 2013: Audio-based guitar tablature transcription using multipitch analysis and playability constraints](https://doi.org/10.1109/ICASSP.2013.6637636)：
  展示用可彈指位限制及時間連續性改善轉錄的路線；其實驗以合成吉他資料評估，
  數字不能直接套用到本專案的分軌錄音。
- [Noise2Fret, 2026](https://arxiv.org/abs/2608.30854)：
  將音高、指位距離與手掌跨度等代價納入訓練，是可進一步研究的方向，
  本專案未整合或重現該模型。
