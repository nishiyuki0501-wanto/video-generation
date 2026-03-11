#!/usr/bin/env python3
"""
analyze_media.py
================
動画を分析して analysis/*.json を生成する。
これがパイプライン全体の土台。ここが弱いと後工程がすべて不安定になる。

使い方:
  python scripts/analysis/analyze_media.py input/source.mp4 \
      --preset presets/tutorial-balanced-ja.yaml \
      --out-dir analysis/

依存:
  pip install opencv-python-headless faster-whisper ffmpeg-python numpy pillow webrtcvad pyyaml
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import yaml


# ────────────────────────────────────────────
# ユーティリティ
# ────────────────────────────────────────────

def load_preset(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def save_json(data: dict, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {path}")


# ────────────────────────────────────────────
# 1. media.json — 動画メタデータ（ffprobe）
# ────────────────────────────────────────────

def analyze_media(video_path: str) -> dict:
    print("\n📐 [1/5] メタデータ取得中...")
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    data = json.loads(result.stdout)
    vs = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    as_ = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)

    fps_raw = vs.get("r_frame_rate", "30/1")
    n, d = map(int, fps_raw.split("/"))
    fps = n / d
    duration_ms = int(float(data["format"].get("duration", 0)) * 1000)

    result = {
        "source_path": video_path,
        "duration_ms": duration_ms,
        "fps": round(fps, 3),
        "total_frames": int(duration_ms / 1000 * fps),
        "width": int(vs.get("width", 1920)),
        "height": int(vs.get("height", 1080)),
        "codec": vs.get("codec_name", "unknown"),
        "audio_channels": int(as_["channels"]) if as_ else 0,
        "audio_sample_rate": int(as_["sample_rate"]) if as_ else 0,
        "has_audio": as_ is not None,
        "file_size_bytes": os.path.getsize(video_path),
    }
    print(f"  解像度: {result['width']}x{result['height']}, "
          f"長さ: {duration_ms/1000:.1f}秒, FPS: {fps:.2f}")
    return result


# ────────────────────────────────────────────
# 2. transcript.json — 音声書き起こし（faster-whisper）
# ────────────────────────────────────────────

def transcribe(video_path: str, preset: dict) -> dict:
    print("\n🎤 [2/5] 音声書き起こし中（faster-whisper）...")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("  ⚠️  faster-whisper が見つかりません。スキップします。")
        print("     pip install faster-whisper でインストールしてください。")
        return {"segments": [], "language": "ja", "overall_confidence": 0.0,
                "_skipped": True, "_reason": "faster-whisper not installed"}

    model_name = preset.get("analysis", {}).get("whisper_model", "medium")
    print(f"  モデル: {model_name}（初回はダウンロードが発生します）")

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(
        video_path,
        language="ja",
        word_timestamps=True,
        vad_filter=False,  # VADは別途 webrtcvad で行う
    )

    segments = []
    all_confidences = []

    for seg in segments_iter:
        words = []
        for w in (seg.words or []):
            words.append({
                "word": w.word.strip(),
                "start_ms": int(w.start * 1000),
                "end_ms": int(w.end * 1000),
                "confidence": round(w.probability, 3),
            })
            all_confidences.append(w.probability)

        segments.append({
            "start_ms": int(seg.start * 1000),
            "end_ms": int(seg.end * 1000),
            "text": seg.text.strip(),
            "confidence": round(sum(w["confidence"] for w in words) / max(len(words), 1), 3),
            "words": words,
        })
        print(f"  [{seg.start:.1f}s] {seg.text.strip()[:60]}")

    overall = round(sum(all_confidences) / max(len(all_confidences), 1), 3)
    print(f"  全体信頼度: {overall:.2f} ({len(segments)}セグメント)")

    return {
        "segments": segments,
        "language": info.language,
        "overall_confidence": overall,
    }


# ────────────────────────────────────────────
# 3. vad.json — 音声区間検出（webrtcvad + ffmpeg）
# ────────────────────────────────────────────

def detect_vad(video_path: str, preset: dict) -> dict:
    print("\n🔇 [3/5] 音声/無音区間検出中...")

    # まず ffmpeg でsilencedetect（webrtcvad のフォールバックにも使う）
    silence_via_ffmpeg = _detect_silence_ffmpeg(video_path)

    try:
        import webrtcvad
        result = _detect_vad_webrtcvad(video_path, preset, webrtcvad)
        print(f"  発話区間: {len(result['speech_regions'])}件, "
              f"無音区間: {len(result['silence_regions'])}件 (webrtcvad)")
        return result
    except ImportError:
        print("  ⚠️  webrtcvad が見つかりません。ffmpeg silencedetect で代替します。")
        return _build_vad_from_silence(silence_via_ffmpeg)
    except Exception as e:
        print(f"  ⚠️  webrtcvad エラー: {e}. ffmpeg で代替します。")
        return _build_vad_from_silence(silence_via_ffmpeg)


def _detect_silence_ffmpeg(video_path: str, noise_db: float = -40.0,
                            min_duration: float = 0.3) -> list[dict]:
    """ffmpeg silencedetect で無音区間を取得する。"""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    silences = []
    start = None
    for line in result.stderr.splitlines():
        if "silence_start" in line:
            try:
                start = float(line.split("silence_start:")[1].strip())
            except (IndexError, ValueError):
                pass
        elif "silence_end" in line and start is not None:
            try:
                end = float(line.split("|")[0].split("silence_end:")[1].strip())
                silences.append({
                    "start_ms": int(start * 1000),
                    "end_ms": int(end * 1000),
                    "duration_ms": int((end - start) * 1000),
                })
                start = None
            except (IndexError, ValueError):
                pass
    return silences


def _detect_vad_webrtcvad(video_path: str, preset: dict, webrtcvad) -> dict:
    """webrtcvad でフレーム単位の発話検出を行う。"""
    aggressiveness = preset.get("analysis", {}).get("vad_aggressiveness", 2)
    vad = webrtcvad.Vad(aggressiveness)

    # 音声を 16kHz モノラル PCM に変換
    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as tmp:
        tmp_path = tmp.name

    subprocess.run([
        "ffmpeg", "-i", video_path,
        "-ar", "16000", "-ac", "1", "-f", "s16le",
        tmp_path, "-y", "-loglevel", "error"
    ], check=True)

    with open(tmp_path, "rb") as f:
        pcm = f.read()
    os.unlink(tmp_path)

    frame_ms = 20  # 20ms フレーム
    frame_bytes = int(16000 * frame_ms / 1000) * 2  # 16bit = 2bytes/sample
    frames = [pcm[i:i + frame_bytes] for i in range(0, len(pcm), frame_bytes)
              if len(pcm[i:i + frame_bytes]) == frame_bytes]

    speech_frames = []
    for i, frame in enumerate(frames):
        try:
            is_speech = vad.is_speech(frame, 16000)
        except Exception:
            is_speech = False
        speech_frames.append(is_speech)

    # 連続するフレームをセグメントにまとめる（±2フレームのギャップを埋める）
    speech_regions = []
    silence_regions = []
    in_speech = False
    seg_start = 0

    for i, is_speech in enumerate(speech_frames):
        ms = i * frame_ms
        if is_speech and not in_speech:
            if silence_regions:
                silence_regions[-1]["end_ms"] = ms
                silence_regions[-1]["duration_ms"] = ms - silence_regions[-1]["start_ms"]
            in_speech = True
            seg_start = ms
        elif not is_speech and in_speech:
            speech_regions.append({"start_ms": seg_start, "end_ms": ms})
            in_speech = False
            silence_regions.append({"start_ms": ms, "end_ms": ms, "duration_ms": 0})

    if in_speech:
        speech_regions.append({"start_ms": seg_start, "end_ms": len(frames) * frame_ms})

    return {"speech_regions": speech_regions, "silence_regions": silence_regions}


def _build_vad_from_silence(silence_segments: list[dict]) -> dict:
    """ffmpeg silencedetect の結果から speech/silence regions を構築する。"""
    silence_regions = silence_segments
    # silence の隙間を speech として扱う
    speech_regions = []
    prev_end = 0
    for s in sorted(silence_segments, key=lambda x: x["start_ms"]):
        if s["start_ms"] > prev_end:
            speech_regions.append({"start_ms": prev_end, "end_ms": s["start_ms"]})
        prev_end = s["end_ms"]

    return {"speech_regions": speech_regions, "silence_regions": silence_regions}


# ────────────────────────────────────────────
# 4. ui-events.json — UIイベント検出（OpenCV）
# ────────────────────────────────────────────

def detect_ui_events(video_path: str, preset: dict) -> dict:
    print("\n🖱️  [4/5] UIイベント検出中（OpenCV）...")
    cfg = preset.get("analysis", {})
    scene_threshold = cfg.get("scene_change_threshold", 30.0)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    events = []
    prev_gray = None
    frame_idx = 0

    # カーソル追跡用の状態
    cursor_positions = []  # (frame_idx, x, y)
    cursor_pause_start = None
    cursor_pause_pos = None
    PAUSE_THRESHOLD_FRAMES = int(fps * 2.0)  # 2秒間停止でpause
    MOVE_THRESHOLD_PX = 5  # ピクセル単位の移動閾値

    print("  フレーム解析中...", end="", flush=True)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (320, 180))

        if prev_gray is not None:
            diff = cv2.absdiff(small, prev_gray)
            mean_diff = float(np.mean(diff))
            ms = int(frame_idx / fps * 1000)

            # シーン変化検出
            if mean_diff > scene_threshold:
                events.append({
                    "type": "scene_change",
                    "start_ms": ms,
                    "end_ms": ms + int(1000 / fps),
                    "bbox": {"x": 0, "y": 0, "w": 1.0, "h": 1.0},
                    "confidence": min(1.0, mean_diff / (scene_threshold * 3)),
                    "score": round(mean_diff, 2),
                })

            # クリック候補の検出（局所的な急激な変化）
            # 差分画像の局所最大値を探す
            max_val = float(np.max(diff))
            if max_val > 60 and mean_diff < 15:  # 局所変化だが全体は静か
                # 変化が最大の位置を特定
                _, _, _, max_loc = cv2.minMaxLoc(diff)
                # 320x180 → 元の解像度に正規化
                cx_norm = max_loc[0] / 320
                cy_norm = max_loc[1] / 180
                # bbox size（小さい = クリック候補の可能性）
                region_size = float(np.sum(diff > 40)) / (320 * 180)

                events.append({
                    "type": "click",
                    "start_ms": ms - int(200),
                    "end_ms": ms + int(400),
                    "bbox": {
                        "x": max(0, cx_norm - 0.04),
                        "y": max(0, cy_norm - 0.04),
                        "w": min(0.08, region_size * 3),
                        "h": min(0.08, region_size * 3),
                    },
                    "confidence": min(0.9, max_val / 120),
                    "area_ratio": round(region_size, 4),
                })

            # タイピング候補の検出（小領域で断続的な変化）
            if 3 < mean_diff < 15:
                # 変化が小さい矩形領域に集中しているか確認
                diff_thresh = (diff > 20).astype(np.uint8)
                contours, _ = cv2.findContours(
                    diff_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                if contours:
                    max_cnt = max(contours, key=cv2.contourArea)
                    x, y, bw, bh = cv2.boundingRect(max_cnt)
                    aspect = bw / max(bh, 1)
                    if aspect > 3 and bh < 20:  # 横長の細い領域 = 入力欄
                        events.append({
                            "type": "typing",
                            "start_ms": ms,
                            "end_ms": ms + int(1000 / fps),
                            "bbox": {
                                "x": x / 320, "y": y / 180,
                                "w": bw / 320, "h": bh / 180,
                            },
                            "confidence": 0.55,
                        })

        prev_gray = small
        frame_idx += 1
        if frame_idx % 300 == 0:
            print(".", end="", flush=True)

    cap.release()
    print(f" 完了（{len(events)}イベント）")

    # 近接したイベントをマージ（100ms以内の同タイプ）
    events = _merge_nearby_events(events)

    return {"events": events}


def _merge_nearby_events(events: list[dict], gap_ms: int = 100) -> list[dict]:
    """近接した同タイプのイベントをマージする。"""
    if not events:
        return []
    events = sorted(events, key=lambda e: (e["type"], e["start_ms"]))
    merged = [events[0]]
    for ev in events[1:]:
        last = merged[-1]
        if (ev["type"] == last["type"] and
                ev["start_ms"] - last["end_ms"] < gap_ms):
            last["end_ms"] = max(last["end_ms"], ev["end_ms"])
            last["confidence"] = max(last["confidence"], ev["confidence"])
        else:
            merged.append(ev)
    return sorted(merged, key=lambda e: e["start_ms"])


# ────────────────────────────────────────────
# 5. ocr.json — 画面テキスト認識（EasyOCR）
# ────────────────────────────────────────────

def run_ocr(video_path: str, preset: dict, interval_sec: float = 2.0) -> dict:
    """EasyOCR でフレームのテキストを認識する。"""
    print("\n🔤 [5/5] OCR（画面テキスト認識）中...")
    try:
        import easyocr
    except ImportError:
        print("  ⚠️  easyocr が見つかりません。スキップします。")
        print("     pip install easyocr でインストールしてください。")
        return {"entries": [], "_skipped": True, "_reason": "easyocr not installed"}

    reader = easyocr.Reader(["ja", "en"], verbose=False)
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_every = max(1, int(fps * interval_sec))

    entries = []
    frame_idx = 0
    print("  OCR中（時間がかかります）...", end="", flush=True)

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_every == 0:
            ms = int(frame_idx / fps * 1000)
            try:
                results = reader.readtext(frame)
                for (bbox_pts, text, conf) in results:
                    if conf < 0.5 or len(text.strip()) < 2:
                        continue
                    pts = np.array(bbox_pts)
                    x, y = float(pts[:, 0].min()) / frame.shape[1], float(pts[:, 1].min()) / frame.shape[0]
                    w = float(pts[:, 0].max() - pts[:, 0].min()) / frame.shape[1]
                    h = float(pts[:, 1].max() - pts[:, 1].min()) / frame.shape[0]
                    entries.append({
                        "start_ms": ms,
                        "end_ms": ms + int(interval_sec * 1000),
                        "text": text.strip(),
                        "bbox": {"x": round(x, 3), "y": round(y, 3),
                                 "w": round(w, 3), "h": round(h, 3)},
                        "confidence": round(conf, 3),
                    })
            except Exception:
                pass
            if frame_idx % (sample_every * 10) == 0:
                print(".", end="", flush=True)
        frame_idx += 1

    cap.release()
    print(f" 完了（{len(entries)}テキスト）")
    return {"entries": entries}


# ────────────────────────────────────────────
# メイン
# ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="動画を分析して analysis/*.json を生成する（パイプライン Step 1）"
    )
    parser.add_argument("video_path", help="分析する動画ファイルのパス")
    parser.add_argument("--preset", default="presets/tutorial-balanced-ja.yaml",
                        help="プリセットYAMLのパス")
    parser.add_argument("--out-dir", default="analysis",
                        help="出力先ディレクトリ（デフォルト: analysis/）")
    parser.add_argument("--skip-ocr", action="store_true",
                        help="OCRをスキップする（重い処理）")

    args = parser.parse_args()

    if not os.path.exists(args.video_path):
        print(f"❌ 動画ファイルが見つかりません: {args.video_path}")
        sys.exit(1)

    preset = load_preset(args.preset) if os.path.exists(args.preset) else {}
    out = args.out_dir

    print(f"\n🎬 動画分析開始: {args.video_path}")
    print(f"   プリセット: {args.preset}")
    print("=" * 60)

    # Step 1: メタデータ
    media = analyze_media(args.video_path)
    save_json(media, f"{out}/media.json")

    # Step 2: 書き起こし
    transcript = transcribe(args.video_path, preset)
    save_json(transcript, f"{out}/transcript.json")

    # Step 3: VAD
    vad = detect_vad(args.video_path, preset)
    save_json(vad, f"{out}/vad.json")

    # Step 4: UIイベント
    ui_events = detect_ui_events(args.video_path, preset)
    save_json(ui_events, f"{out}/ui-events.json")

    # Step 5: OCR（プリセットで有効かつ --skip-ocr でない場合のみ）
    enable_ocr = preset.get("analysis", {}).get("enable_ocr", False) and not args.skip_ocr
    if enable_ocr:
        ocr = run_ocr(args.video_path, preset)
    else:
        print("\n🔤 [5/5] OCR: スキップ（preset.enable_ocr=false または --skip-ocr）")
        ocr = {"entries": [], "_skipped": True, "_reason": "disabled in preset"}
    save_json(ocr, f"{out}/ocr.json")

    # サマリー
    print("\n" + "=" * 60)
    print("✅ 分析完了")
    print(f"  動画長さ:       {media['duration_ms']/1000:.1f}秒")
    print(f"  書き起こし信頼度: {transcript.get('overall_confidence', 0):.2f}")
    print(f"  発話区間:        {len(vad.get('speech_regions', []))}件")
    print(f"  無音区間:        {len(vad.get('silence_regions', []))}件")
    print(f"  UIイベント:      {len(ui_events.get('events', []))}件")
    print(f"\n💡 次のステップ:")
    print(f"   python scripts/edit/plan_cuts.py --preset {args.preset}")

    if transcript.get("overall_confidence", 1.0) < 0.6:
        print("\n  ⚠️  WARNING: 書き起こし信頼度が低い（< 0.6）です。")
        print("     カット・字幕の精度が下がります。プリセットの fallback_policy を確認してください。")


if __name__ == "__main__":
    main()
