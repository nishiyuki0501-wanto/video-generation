#!/usr/bin/env python3
"""
plan_speed.py
=============
edits/cut-plan.json を元に、各 keep 区間の再生速度を決定する（Step 3）。

使い方:
  python scripts/edit/plan_speed.py \
      --analysis-dir analysis/ \
      --cut-plan edits/cut-plan.json \
      --preset presets/tutorial-balanced-ja.yaml \
      --output edits/speed-plan.json
"""

import argparse
import json
import os
import yaml


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(data, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {path}")

def load_preset(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify_speed(seg: dict, transcript_segs: list, ui_events: list,
                   vad_silence: list, preset_speed: dict) -> tuple[float, str, bool]:
    """
    セグメントの速度・ミュートフラグ・理由を返す。
    Returns: (speed, reason, mute_audio)
    """
    start_ms = seg["start_ms"]
    end_ms = seg["end_ms"]
    dur_ms = end_ms - start_ms

    # このセグメント内に発話があるか
    has_speech = any(
        ts["start_ms"] < end_ms and ts["end_ms"] > start_ms
        for ts in transcript_segs
    )

    # このセグメント内にUIイベントがあるか
    has_click = any(
        ev["start_ms"] < end_ms and ev["end_ms"] > start_ms
        and ev["type"] in ("click", "modal_open")
        for ev in ui_events
    )
    has_typing = any(
        ev["start_ms"] < end_ms and ev["end_ms"] > start_ms
        and ev["type"] == "typing"
        for ev in ui_events
    )

    # 完全な無音区間かどうか（VADで確認）
    is_full_silence = any(
        s["start_ms"] <= start_ms and s["end_ms"] >= end_ms
        for s in vad_silence
    )

    mute_above = preset_speed.get("mute_audio_above_speed", 1.75)

    # 速度判定
    if has_speech and has_click:
        # 発話しながらクリック操作 → 等速
        speed = 1.0
        reason = "spoken instruction with UI interaction"
    elif has_speech:
        # 発話区間
        max_spoken = preset_speed.get("spoken_segment_max_speed", 1.10)
        speed = max_spoken
        reason = f"spoken segment (max {max_spoken}x)"
    elif has_typing:
        # タイピング実演
        speed = preset_speed.get("typing_demo_speed", 1.25)
        reason = "typing demonstration"
    elif has_click:
        # クリックのみ（保護区間はすでに cut されていないはず）
        speed = preset_speed.get("ui_navigation_speed", 1.35)
        reason = "UI click navigation"
    elif is_full_silence and dur_ms > 30000:
        # 長い待機（30秒以上）
        speed = preset_speed.get("long_wait_loading_speed", 6.0)
        reason = f"long wait/loading ({dur_ms/1000:.0f}s)"
    elif is_full_silence or not has_speech:
        # 短い無音・ローディング
        speed = preset_speed.get("loading_speed", 3.0)
        reason = "loading or inactive screen"
    else:
        speed = preset_speed.get("ui_navigation_speed", 1.35)
        reason = "UI navigation"

    mute_audio = speed > mute_above

    return speed, reason, mute_audio


def plan_speed(analysis_dir: str, cut_plan_path: str, preset: dict, output_path: str):
    cut_plan = load_json(cut_plan_path)
    transcript = load_json(f"{analysis_dir}/transcript.json")
    ui_events_data = load_json(f"{analysis_dir}/ui-events.json")
    vad = load_json(f"{analysis_dir}/vad.json")

    preset_speed = preset.get("speed", {})
    transcript_segs = transcript.get("segments", [])
    ui_events = ui_events_data.get("events", [])
    silence_regions = vad.get("silence_regions", [])

    segments = []
    for seg in cut_plan["segments"]:
        if seg["action"] == "cut":
            continue  # カット区間はスキップ

        speed, reason, mute = classify_speed(
            seg, transcript_segs, ui_events, silence_regions, preset_speed
        )

        segments.append({
            "start_ms": seg["start_ms"],
            "end_ms": seg["end_ms"],
            "speed": speed,
            "reason": reason,
            "confidence": 0.80,
            "mute_audio": mute,
        })

    # 統計
    sped_up = [s for s in segments if s["speed"] > 1.0]
    time_saved = sum(
        (s["end_ms"] - s["start_ms"]) * (1 - 1/s["speed"]) / 1000
        for s in sped_up
    )
    print(f"  速度変更: {len(sped_up)}区間（約{time_saved:.0f}秒の短縮）")

    result = {
        "generated_from_preset": preset.get("preset_id", "unknown"),
        "segments": segments,
        "estimated_time_saved_ms": int(time_saved * 1000),
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="カット計画を元に速度計画を生成する（Step 3）")
    parser.add_argument("--analysis-dir", default="analysis")
    parser.add_argument("--cut-plan", default="edits/cut-plan.json")
    parser.add_argument("--preset", default="presets/tutorial-balanced-ja.yaml")
    parser.add_argument("--output", default="edits/speed-plan.json")
    args = parser.parse_args()

    print("\n⏩ 速度計画生成中...")
    preset = load_preset(args.preset)
    result = plan_speed(args.analysis_dir, args.cut_plan, preset, args.output)
    save_json(result, args.output)
    print(f"\n💡 次のステップ:")
    print(f"   python scripts/edit/plan_zoom.py --preset {args.preset}")


if __name__ == "__main__":
    main()
