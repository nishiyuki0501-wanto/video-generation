#!/usr/bin/env python3
"""
plan_zoom.py
============
UIイベント・OCRを元にズーム計画を生成する（Step 4）。

使い方:
  python scripts/edit/plan_zoom.py \
      --analysis-dir analysis/ \
      --cut-plan edits/cut-plan.json \
      --speed-plan edits/speed-plan.json \
      --preset presets/tutorial-balanced-ja.yaml \
      --output edits/zoom-plan.json
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


def is_small_ui(bbox: dict) -> tuple[bool, float]:
    """UIが小さいかどうかを判定する。面積比を返す。"""
    area = bbox.get("w", 0) * bbox.get("h", 0)
    return area < 0.05, area  # 5%未満なら小さい


def get_speed_at(ms: int, speed_segments: list) -> float:
    """指定時刻の速度を返す。"""
    for seg in speed_segments:
        if seg["start_ms"] <= ms < seg["end_ms"]:
            return seg["speed"]
    return 1.0


def compute_zoom_scale(bbox: dict, preset_zoom: dict) -> float:
    """bbox のサイズに応じたズーム倍率を返す。"""
    area = bbox.get("w", 0) * bbox.get("h", 0)
    if area < 0.01:
        return preset_zoom.get("scale_tiny_ui", 1.60)
    elif area < 0.03:
        return preset_zoom.get("scale_small_ui", 1.45)
    else:
        return preset_zoom.get("scale_default", 1.28)


def check_zoom_valid(center_x: float, center_y: float, scale: float) -> tuple[bool, str]:
    """ズーム後にターゲットがフレーム外に出ないか確認する。"""
    half = 0.5 / scale
    if center_x - half < 0 or center_x + half > 1:
        return False, f"x out of bounds ({center_x:.2f} ± {half:.2f})"
    if center_y - half < 0 or center_y + half > 1:
        return False, f"y out of bounds ({center_y:.2f} ± {half:.2f})"
    return True, ""


def is_in_cut_zone(start_ms: int, end_ms: int, cut_segments: list) -> bool:
    """区間がカット区間と重なるか確認する。"""
    for seg in cut_segments:
        if seg["action"] == "cut":
            if seg["start_ms"] < end_ms and seg["end_ms"] > start_ms:
                return True
    return False


def plan_zoom(analysis_dir: str, cut_plan_path: str, speed_plan_path: str,
              preset: dict, output_path: str):
    ui_events_data = load_json(f"{analysis_dir}/ui-events.json")
    cut_plan = load_json(cut_plan_path)
    speed_plan = load_json(speed_plan_path)

    # ocr.json は任意
    ocr_path = f"{analysis_dir}/ocr.json"
    ocr = load_json(ocr_path) if os.path.exists(ocr_path) else {"entries": []}

    preset_zoom = preset.get("zoom", {})
    if not preset_zoom.get("enabled", True):
        print("  ℹ️  ズームはプリセットで無効化されています。")
        save_json({"events": [], "disabled_by_preset": True}, output_path)
        return {"events": []}

    min_dur_ms = preset_zoom.get("min_event_duration_ms", 600)
    min_gap_ms = preset_zoom.get("min_gap_between_zooms_ms", 500)
    max_coverage = preset_zoom.get("max_zoom_coverage_ratio", 0.70)
    ease_in = preset_zoom.get("ease_in_ms", 220)
    ease_out = preset_zoom.get("ease_out_ms", 180)

    cut_segments = cut_plan["segments"]
    speed_segments = speed_plan["segments"]

    zoom_candidates = []

    # UIイベントからズーム候補を収集
    for ev in ui_events_data.get("events", []):
        if ev["type"] not in ("click", "cursor_pause", "typing", "modal_open"):
            continue
        if ev["confidence"] < 0.6:
            continue
        if is_in_cut_zone(ev["start_ms"], ev["end_ms"], cut_segments):
            continue

        dur = ev["end_ms"] - ev["start_ms"]
        if dur < min_dur_ms:
            continue

        speed = get_speed_at(ev["start_ms"], speed_segments)
        if speed > 2.0:
            continue  # 高速再生区間はズームしない

        bbox = ev.get("bbox", {"x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1})
        small, area = is_small_ui(bbox)

        if ev["type"] == "modal_open":
            # モーダルはサイズに関わらずズーム候補
            pass
        elif not small:
            continue  # 大きい UI はズームしない

        center_x = bbox["x"] + bbox["w"] / 2
        center_y = bbox["y"] + bbox["h"] / 2
        scale = compute_zoom_scale(bbox, preset_zoom)

        valid, reason = check_zoom_valid(center_x, center_y, scale)
        if not valid:
            # スケールを下げて再試行
            scale = preset_zoom.get("scale_default", 1.28)
            valid, reason = check_zoom_valid(center_x, center_y, scale)

        zoom_candidates.append({
            "start_ms": max(0, ev["start_ms"] - ease_in),
            "end_ms": ev["end_ms"] + ease_out,
            "center_x": round(center_x, 3),
            "center_y": round(center_y, 3),
            "scale": scale,
            "reason": f"{ev['type']} (area: {area:.3f})",
            "confidence": ev["confidence"],
            "ease_in_ms": ease_in,
            "ease_out_ms": ease_out,
            "disabled": not valid,
            "disabled_reason": reason if not valid else None,
        })

    # OCRからズーム候補を追加
    for entry in ocr.get("entries", []):
        if entry.get("confidence", 0) < 0.6:
            continue
        bbox = entry.get("bbox", {})
        area = bbox.get("w", 0) * bbox.get("h", 0)
        if area > 0.03:  # 十分大きいテキストはズーム不要
            continue

        zoom_candidates.append({
            "start_ms": entry["start_ms"],
            "end_ms": entry["end_ms"],
            "center_x": round(bbox["x"] + bbox["w"] / 2, 3),
            "center_y": round(bbox["y"] + bbox["h"] / 2, 3),
            "scale": preset_zoom.get("scale_small_ui", 1.45),
            "reason": f"OCR small text: '{entry['text'][:20]}'",
            "confidence": entry["confidence"],
            "ease_in_ms": ease_in,
            "ease_out_ms": ease_out,
            "disabled": False,
            "disabled_reason": None,
        })

    # 連続ズームを防ぐ（min_gap_ms 以内の連続ズームを後者を無効化）
    sorted_cands = sorted(zoom_candidates, key=lambda z: z["start_ms"])
    filtered = []
    last_end = -999999
    for z in sorted_cands:
        if z["disabled"]:
            filtered.append(z)
            continue
        if z["start_ms"] - last_end < min_gap_ms:
            z = dict(z)
            z["disabled"] = True
            z["disabled_reason"] = f"too close to previous zoom (gap: {z['start_ms'] - last_end}ms)"
        else:
            last_end = z["end_ms"]
        filtered.append(z)

    # カバレッジが超過していないか確認
    total_duration = sum(
        s["end_ms"] - s["start_ms"]
        for s in cut_segments if s["action"] == "keep"
    )
    zoom_duration = sum(
        z["end_ms"] - z["start_ms"]
        for z in filtered if not z.get("disabled")
    )
    coverage = zoom_duration / max(total_duration, 1)
    if coverage > max_coverage:
        print(f"  ⚠️  ズームカバレッジ超過 ({coverage:.1%} > {max_coverage:.0%})"
              "信頼度の低い候補を無効化します。")
        # 信頼度の低いものから無効化
        for z in sorted(filtered, key=lambda z: z["confidence"]):
            if not z.get("disabled"):
                z["disabled"] = True
                z["disabled_reason"] = "coverage limit exceeded"
                zoom_duration -= z["end_ms"] - z["start_ms"]
                if zoom_duration / max(total_duration, 1) <= max_coverage:
                    break

    active = [z for z in filtered if not z.get("disabled")]
    disabled = [z for z in filtered if z.get("disabled")]
    print(f"  ズーム: {len(active)}件有効, {len(disabled)}件無効化")

    result = {
        "generated_from_preset": preset.get("preset_id", "unknown"),
        "events": filtered,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="ズーム計画を生成する（Step 4）")
    parser.add_argument("--analysis-dir", default="analysis")
    parser.add_argument("--cut-plan", default="edits/cut-plan.json")
    parser.add_argument("--speed-plan", default="edits/speed-plan.json")
    parser.add_argument("--preset", default="presets/tutorial-balanced-ja.yaml")
    parser.add_argument("--output", default="edits/zoom-plan.json")
    args = parser.parse_args()

    print("\n🔍 ズーム計画生成中...")
    preset = load_preset(args.preset)
    result = plan_zoom(args.analysis_dir, args.cut_plan, args.speed_plan, preset, args.output)
    save_json(result, args.output)
    print(f"\n💡 次のステップ:")
    print(f"   python scripts/edit/plan_subtitles.py --preset {args.preset}")


if __name__ == "__main__":
    main()
