# 05: generate_audio.py の詳細ロジック

narration/generate_audio.py をスキルが動的生成して実行する。

## 定数設定

```python
SPEAKER_ID   = 2       # ユーザーが選んだ話者ID
FFMPEG       = "/opt/homebrew/bin/ffmpeg"
VOICEVOX_URL = "http://localhost:50021"
SAMPLE_RATE  = 24000   # VOICEVOX デフォルト（固定）
```

## A. master.mp4上のナレーション位置を計算

narration-script.jsonの scene_start_sec/scene_end_sec はソース動画の座標。
master.mp4上の位置は cut-plan.json から逆算する。

```python
from collections import defaultdict

kept_clips = [c for c in cut_plan["clips"] if c.get("keep", False)]
pos = 0.0
narr_master = defaultdict(lambda: {"start": float("inf"), "end": 0.0})
for clip in kept_clips:
    dur = clip.get("trim_to_sec") or (clip["source_end_sec"] - clip["source_start_sec"])
    nid = clip.get("narration_id")
    if nid:
        narr_master[nid]["start"] = min(narr_master[nid]["start"], pos)
        narr_master[nid]["end"]   = max(narr_master[nid]["end"],   pos + dur)
    pos += dur
video_total_sec = pos
```

## B. セグメントリスト構築（narration + silence）

```python
segments = []
cursor = 0.0
for n in sorted(narrations, key=lambda x: x["id"]):
    ns = narr_master[n["id"]]["start"]
    ne = narr_master[n["id"]]["end"]
    if ns > cursor + 0.001:
        segments.append(("silence", cursor, ns))     # ギャップ埋め
    segments.append(("narration", ns, ne, n["text"], n["id"]))
    cursor = ne
if video_total_sec > cursor + 0.001:
    segments.append(("silence", cursor, video_total_sec))  # 末尾
```

## C. silence WAV生成

```python
def make_silence(path, duration_sec):
    subprocess.run([
        FFMPEG, "-y", "-f", "lavfi",
        "-i", f"anullsrc=r={SAMPLE_RATE}:cl=mono",
        "-t", str(duration_sec),
        "-acodec", "pcm_s16le", path
    ], capture_output=True, check=True)
```

## D. narration WAV生成（VOICEVOX + apadパディング）

```python
import wave

def wav_duration(path):
    with wave.open(path, 'rb') as w:
        return w.getnframes() / w.getframerate()

def make_narration_wav(text, speaker_id, scene_sec, raw_path, padded_path):
    # Step1: audio_query
    r = requests.post(f"{VOICEVOX_URL}/audio_query",
                      params={"text": text, "speaker": speaker_id}, timeout=30)
    r.raise_for_status()
    # Step2: synthesis
    r2 = requests.post(f"{VOICEVOX_URL}/synthesis",
                       params={"speaker": speaker_id},
                       json=r.json(),
                       headers={"Content-Type": "application/json"}, timeout=60)
    r2.raise_for_status()
    with open(raw_path, "wb") as f:
        f.write(r2.content)
    audio_sec = wav_duration(raw_path)
    pad_sec = max(0.0, scene_sec - audio_sec)
    subprocess.run([
        FFMPEG, "-y", "-i", raw_path,
        "-af", f"apad=pad_dur={pad_sec:.6f}",
        "-t", f"{scene_sec:.6f}",
        "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
        padded_path
    ], capture_output=True, check=True)
    return audio_sec, pad_sec
```

## E. 全WAVをconcat → narration.wav

```python
# concat_audio.txt の形式
with open(concat_txt, "w") as f:
    for wav_path in wav_files:
        f.write(f"file '{wav_path}'\n")

subprocess.run([
    FFMPEG, "-y", "-f", "concat", "-safe", "0",
    "-i", concat_txt,
    "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
    narration_wav
], check=True, capture_output=True)
```

長さ検証：
```python
actual = wav_duration(narration_wav)
diff = actual - video_total_sec
print(f"narration.wav: {actual:.3f}s, diff: {diff:+.3f}s")
# ±0.1秒以内なら問題なし（-shortestフラグで吸収）
```

## F. final.mp4 合成（元音声を削除）

```bash
/opt/homebrew/bin/ffmpeg -y \
  -i output/master.mp4 \
  -i narration/audio/narration.wav \
  -map 0:v:0 \
  -map 1:a:0 \
  -c:v copy \
  -c:a aac -b:a 192k \
  -shortest \
  output/final.mp4
```

`-map 0:v:0 -map 1:a:0` で元動画の音声トラックを完全に除外し、narration.wavのみを使う。
