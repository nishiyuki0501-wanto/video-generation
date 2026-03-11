# 01: Whisper 文字起こし

faster-whisperのmediumモデルでタイムスタンプ付き文字起こしを行う。

## 実行

```bash
python scripts/transcribe.py input/source.mp4
```

出力: `analysis/transcript.json`

## スクリプト概要

```python
from faster_whisper import WhisperModel
model = WhisperModel("medium", device="cpu", compute_type="int8")
segments, info = model.transcribe(video_path, language="ja", beam_size=5)
```

## 出力フォーマット

```json
{
  "segments": [
    {"start_sec": 0.0, "end_sec": 3.5, "text": "まず設定画面を開きます"},
    {"start_sec": 3.5, "end_sec": 7.2, "text": "ここにAPIキーを入力します"}
  ],
  "duration_sec": 342.0
}
```
