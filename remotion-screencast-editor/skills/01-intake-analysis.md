---
name: intake-analysis
description: "動画・音声・字幕・UIイベントの分析を行い、編集判断に必要な中間データを作る"
when_to_use:
  - "入力動画が追加または更新されたとき"
  - "analysis/*.json が存在しないとき"
inputs:
  - "input/source.mp4"
  - "presets/{active_preset}.yaml → analysis.* セクション"
outputs:
  - "analysis/media.json"
  - "analysis/transcript.json"
  - "analysis/vad.json"
  - "analysis/ui-events.json"
  - "analysis/ocr.json（preset で enable_ocr: true の場合のみ）"
---

# Objective
カット・速度・ズーム・字幕の判断に必要な分析結果をすべて生成する。
ここが弱いと後工程が全部不安定になる。土台として最も重要なステップ。

# 実行コマンド

```bash
python scripts/analysis/analyze_media.py input/source.mp4 \
  --preset presets/tutorial-balanced-ja.yaml \
  --out-dir analysis/
```

# 各分析の内容と判断基準

## 1. media.json — 動画メタデータ
ffprobe で取得する。

取得項目：
- source_path, duration_ms, fps
- width, height, audio_channels, audio_sample_rate
- file_size_bytes

## 2. transcript.json — 音声書き起こし（Whisper）
faster-whisper を使う。word_timestamps=True で必ず単語レベルのタイムスタンプを取る。

```json
{
  "segments": [
    {
      "start_ms": 1200,
      "end_ms": 4800,
      "text": "まず設定画面を開きます",
      "confidence": 0.94,
      "words": [
        {"word": "まず", "start_ms": 1200, "end_ms": 1550, "confidence": 0.97},
        {"word": "設定", "start_ms": 1600, "end_ms": 1950, "confidence": 0.93}
      ]
    }
  ],
  "language": "ja",
  "overall_confidence": 0.91
}
```

**判断ルール：**
- overall_confidence < 0.6 → 全ての cut 判断を conservative に固定、字幕を簡易字幕にフラグ
- 単語 confidence < 0.5 → その単語周辺をカット禁止エリアにする

## 3. vad.json — 音声区間検出（webrtcvad）
発話/無音を正確に分離する。

```json
{
  "speech_regions": [
    {"start_ms": 1200, "end_ms": 4800},
    {"start_ms": 5100, "end_ms": 8300}
  ],
  "silence_regions": [
    {"start_ms": 0, "end_ms": 1200, "duration_ms": 1200},
    {"start_ms": 4800, "end_ms": 5100, "duration_ms": 300}
  ]
}
```

**注意：**
- VADの無音 ≠ 必ずカット。UIが動いている場合は速度変更候補に回す。
- transcript と突き合わせて矛盾がないか確認する。

## 4. ui-events.json — UIイベント検出（OpenCV）
フレーム差分・マウスカーソル座標の変化から推定する。

イベントタイプ：
- `click` — カーソルが一点に停止後、フレーム差分が急増
- `cursor_pause` — カーソルが2秒以上停止（重要箇所を指している可能性）
- `typing` — 小領域で断続的なフレーム差分
- `scroll` — 縦方向の大きなフレームシフト
- `modal_open` — 突発的なオーバーレイ出現（差分が大きい）
- `scene_change` — 全体の輝度差分が閾値を超える

```json
{
  "events": [
    {
      "type": "click",
      "start_ms": 3200,
      "end_ms": 3400,
      "bbox": {"x": 0.72, "y": 0.15, "w": 0.08, "h": 0.04},
      "confidence": 0.82
    }
  ]
}
```

**信頼性の扱い：**
- confidence < 0.6 → zoom 候補から除外
- click/typing は保護区間として cut を禁止する
- cursor_pause は zoom トリガーの参考情報として使う

## 5. ocr.json — 画面内テキスト認識（EasyOCR）
preset で enable_ocr: true の場合のみ実行。重い処理なのでデフォルト off。

用途：
- 小さいダイアログ・エラーメッセージ → zoom 候補
- ターミナル出力 → 重要区間として保護
- 設定値・コマンド → 字幕の custom_terms と照合

# 失敗時のフォールバック

| 状況 | フォールバック |
|------|----------------|
| Whisper が動かない | transcript = null、全カットを禁止、字幕を空に |
| webrtcvad が動かない | VAD = null、silence_regions は ffmpeg silencedetect で代替 |
| cursor検出が不安定 | ui-events の confidence を全て 0.5 に下げる |
| OCRが動かない | ocr.json = null（ズーム精度が下がるが続行可能） |

# downstream への引き継ぎ事項

analysis 完了後、以下を cut-skill に伝える：
- transcript.overall_confidence
- 保護区間リスト（click/typing のある区間）
- silence_regions のうち duration_ms が長いもの（速度変更候補）
