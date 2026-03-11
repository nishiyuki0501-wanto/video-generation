#!/usr/bin/env python3
"""
narration-video-producer: Step 1 - 文字起こし
Usage: python scripts/transcribe.py input/source.mp4
"""
import sys
import json
import os
from pathlib import Path

def transcribe(video_path: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("❌ faster-whisper が必要です: pip install faster-whisper")
        sys.exit(1)

    video_path = Path(video_path).resolve()
    if not video_path.exists():
        print(f"❌ ファイルが見つかりません: {video_path}")
        sys.exit(1)

    base_dir = video_path.parent.parent
    out_dir = base_dir / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "transcript.json"

    print(f"📝 文字起こし開始: {video_path.name}")
    print("⏳ モデル読み込み中 (medium, int8)...")

    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        str(video_path), language="ja", beam_size=5
    )

    segments = []
    for seg in segments_iter:
        segments.append({
            "start_sec": round(seg.start, 3),
            "end_sec": round(seg.end, 3),
            "text": seg.text.strip()
        })
        print(f"  [{seg.start:.1f}s - {seg.end:.1f}s] {seg.text.strip()}")

    result = {
        "source": str(video_path),
        "duration_sec": round(info.duration, 3),
        "language": info.language,
        "segments": segments
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完了: {out_path}")
    print(f"   セグメント数: {len(segments)}")
    print(f"   動画長: {info.duration:.1f}s")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/transcribe.py input/source.mp4")
        sys.exit(1)
    transcribe(sys.argv[1])
