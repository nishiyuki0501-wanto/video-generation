#!/usr/bin/env python3
"""
plan_subtitles.py
=================
カット・速度変更後の時間軸に合わせて字幕計画を生成する（Step 5）。
これは最後に実行する。

使い方:
  python scripts/edit/plan_subtitles.py \
      --analysis-dir analysis/ \
      --edits-dir edits/ \
      --preset presets/tutorial-balanced-ja.yaml \
      --output edits/subtitle-plan.json
"""

import argparse
import json
import os
import re
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


# ──────────────────────────────────────────────
# 時間軸の再マッピング
# ──────────────────────────────────────────────

def build_time_map(cut_segments: list, speed_segments: list) -> list[dict]:
    """
    元動画の時間軸 → 出力タイムラインの変換マップを作る。
    各エントリは「このソース区間はこの出力位置から始まる」を表す。
    """
    time_map = []
    output_ms = 0

    for seg in sorted(cut_segments, key=lambda s: s["start_ms"]):
        if seg["action"] == "cut":
            continue

        speed = 1.0
        for sp in speed_segments:
            if sp["start_ms"] <= seg["start_ms"] and sp["end_ms"] >= seg["end_ms"]:
                speed = sp["speed"]
                break

        duration_ms = seg["end_ms"] - seg["start_ms"]
        output_duration_ms = duration_ms / speed

        time_map.append({
            "source_start_ms": seg["start_ms"],
            "source_end_ms": seg["end_ms"],
            "output_start_ms": output_ms,
            "output_end_ms": output_ms + output_duration_ms,
            "speed": speed,
        })
        output_ms += output_duration_ms

    return time_map


def remap_ms(original_ms: int, time_map: list) -> int | None:
    """元動画のタイムスタンプを出力タイムスタンプに変換する。None = カット区間内。"""
    for entry in time_map:
        if entry["source_start_ms"] <= original_ms <= entry["source_end_ms"]:
            delta_source = original_ms - entry["source_start_ms"]
            delta_output = delta_source / entry["speed"]
            return int(entry["output_start_ms"] + delta_output)
    return None  # カットされた区間


# ──────────────────────────────────────────────
# テキスト分割
# ──────────────────────────────────────────────

def split_text_to_lines(text: str, max_chars: int) -> list[str]:
    """テキストを max_chars 以内の行に分割する（句読点優先）。"""
    if len(text) <= max_chars:
        return [text]

    # 句読点で分割
    breakpoints = []
    for i, ch in enumerate(text):
        if ch in ("。", "、", "！", "？", "…", "・"):
            breakpoints.append(i + 1)

    # 句読点での分割を試みる
    for bp in breakpoints:
        if bp <= max_chars:
            part1 = text[:bp]
            part2 = text[bp:]
            if part2:
                return [part1] + split_text_to_lines(part2, max_chars)
            return [part1]

    # 句読点がなければ max_chars で強制分割
    return [text[:max_chars]] + split_text_to_lines(text[max_chars:], max_chars)


def find_highlights(text: str, custom_terms: list[str]) -> list[dict]:
    """ハイライト対象を検出する。"""
    highlights = []

    # カスタム用語
    for term in custom_terms:
        if term in text:
            highlights.append({"text": term, "color": "keyword_color"})

    # ショートカットキー（Ctrl+X, Cmd+K など）
    for m in re.finditer(r'(Ctrl|Cmd|Alt|Shift)\+\w+', text):
        highlights.append({"text": m.group(), "color": "keyword_color"})

    # CLIコマンド（npm/pip/python/git で始まる）
    for m in re.finditer(r'(npm|pip|python|git|cd|ls|mkdir)\s+\S+', text):
        highlights.append({"text": m.group(), "color": "keyword_color"})

    # 重複除去
    seen = set()
    unique = []
    for h in highlights:
        if h["text"] not in seen:
            unique.append(h)
            seen.add(h["text"])

    return unique


def check_subtitle_zoom_conflict(pos: str, start_ms: int, end_ms: int,
                                  zoom_events: list) -> bool:
    """字幕とズームが重なるか確認する（bottom の字幕 と bottom-heavy なズーム）。"""
    for ev in zoom_events:
        if ev.get("disabled"):
            continue
        if ev["start_ms"] < end_ms and ev["end_ms"] > start_ms:
            # ズームのターゲットが画面下半分にある場合は干渉の可能性
            if ev.get("center_y", 0.5) > 0.65 and pos == "bottom":
                return True
    return False


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def plan_subtitles(analysis_dir: str, edits_dir: str, preset: dict, output_path: str):
    transcript = load_json(f"{analysis_dir}/transcript.json")
    cut_plan = load_json(f"{edits_dir}/cut-plan.json")
    speed_plan = load_json(f"{edits_dir}/speed-plan.json")
    zoom_plan = load_json(f"{edits_dir}/zoom-plan.json")

    preset_sub = preset.get("subtitles", {})
    if not preset_sub.get("enabled", True):
        print("  ℹ️  字幕はプリセットで無効化されています。")
        save_json({"cues": [], "disabled_by_preset": True}, output_path)
        return

    max_chars = preset_sub.get("max_chars_per_line", 22)
    max_lines = preset_sub.get("max_lines", 2)
    min_dur = preset_sub.get("min_caption_duration_ms", 900)
    max_dur = preset_sub.get("max_caption_duration_ms", 4200)
    custom_terms = preset_sub.get("custom_terms", [])
    zoom_events = zoom_plan.get("events", [])

    # 時間軸マップを構築
    time_map = build_time_map(cut_plan["segments"], speed_plan["segments"])

    cues = []
    cue_id = 1
    flags = []

    for seg in transcript.get("segments", []):
        # カット区間に含まれているか
        remapped_start = remap_ms(seg["start_ms"], time_map)
        remapped_end = remap_ms(seg["end_ms"], time_map)

        if remapped_start is None or remapped_end is None:
            continue  # カットされた区間

        duration = remapped_end - remapped_start
        text = seg["text"].strip()
        if not text:
            continue

        # 長すぎる字幕を分割
        sub_texts = []
        if duration > max_dur:
            # 単語単位で均等分割
            words = seg.get("words", [])
            if words:
                mid_idx = len(words) // 2
                mid_word = words[mid_idx]
                mid_source_ms = mid_word["start_ms"]
                mid_output_ms = remap_ms(mid_source_ms, time_map)
                if mid_output_ms:
                    sub_texts = [
                        (remapped_start, mid_output_ms,
                         " ".join(w["word"] for w in words[:mid_idx])),
                        (mid_output_ms, remapped_end,
                         " ".join(w["word"] for w in words[mid_idx:])),
                    ]
            if not sub_texts:
                sub_texts = [(remapped_start, remapped_end, text)]
        else:
            sub_texts = [(remapped_start, remapped_end, text)]

        # 短すぎる字幕を最小duration に拡張
        for (s, e, t) in sub_texts:
            actual_dur = e - s
            if actual_dur < min_dur:
                e = s + min_dur

            # 行分割
            lines = split_text_to_lines(t, max_chars)[:max_lines]

            # ハイライト
            highlights = find_highlights(t, custom_terms)

            # 字幕位置（ズームと干渉する場合は上部に移動）
            position = "bottom"
            cue_flags = []
            if check_subtitle_zoom_conflict(position, s, e, zoom_events):
                position = "top"
                cue_flags.append("MOVED_TO_TOP_DUE_TO_ZOOM_OVERLAP")
                flags.append(f"cue_{cue_id:04d}: moved to top")

            cues.append({
                "id": f"cue_{cue_id:04d}",
                "start_ms": int(s),
                "end_ms": int(e),
                "text": t,
                "lines": lines,
                "highlights": highlights,
                "position": position,
                "confidence": seg.get("confidence", 0.8),
                "flags": cue_flags,
            })
            cue_id += 1

    print(f"  字幕: {len(cues)}件生成")
    if flags:
        print(f"  フラグ: {len(flags)}件")

    result = {
        "generated_from_preset": preset.get("preset_id", "unknown"),
        "style": preset_sub.get("style", {}),
        "cues": cues,
        "flags": flags,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="字幕計画を生成する（Step 5）")
    parser.add_argument("--analysis-dir", default="analysis")
    parser.add_argument("--edits-dir", default="edits")
    parser.add_argument("--preset", default="presets/tutorial-balanced-ja.yaml")
    parser.add_argument("--output", default="edits/subtitle-plan.json")
    args = parser.parse_args()

    print("\n📝 字幕計画生成中...")
    preset = load_preset(args.preset)
    result = plan_subtitles(args.analysis_dir, args.edits_dir, preset, args.output)
    if result:
        save_json(result, args.output)
    print(f"\n💡 次のステップ:")
    print(f"   python scripts/render/build_project.py")


if __name__ == "__main__":
    main()
