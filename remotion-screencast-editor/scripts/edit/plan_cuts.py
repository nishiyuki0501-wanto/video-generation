#!/usr/bin/env python3
"""
plan_cuts.py
============
analysis/*.json を読んで edits/cut-plan.json を生成する（パイプライン Step 2）。

使い方:
  python scripts/edit/plan_cuts.py \
      --analysis-dir analysis/ \
      --preset presets/tutorial-balanced-ja.yaml \
      --output edits/cut-plan.json
"""

import argparse
import json
import os
import sys
from pathlib import Path
import yaml


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(data, path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {path}")

def load_preset(path: str) -> dict:
    if not os.path.exists(path):
        print(f"  ⚠️  プリセットが見つかりません: {path}。デフォルト値を使います。")
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────────────
# 保護区間の計算
# ──────────────────────────────────────────────

def build_protected_zones(ui_events: list[dict], transcript_segs: list[dict],
                           preset_cut: dict) -> list[dict]:
    """クリック・タイピングなどの周囲を保護区間として返す。"""
    pre_ms = preset_cut.get("keep_pre_action_ms", 150)
    post_ms = preset_cut.get("keep_post_action_ms", 180)

    zones = []
    for ev in ui_events:
        if ev["type"] in ("click", "typing", "modal_open"):
            zones.append({
                "start_ms": max(0, ev["start_ms"] - pre_ms),
                "end_ms": ev["end_ms"] + post_ms,
                "reason": f"protected: UI action '{ev['type']}' at {ev['start_ms']}ms",
                "confidence": ev.get("confidence", 1.0),
            })

    # 低信頼度の単語周辺も保護
    for seg in transcript_segs:
        for word in seg.get("words", []):
            if word.get("confidence", 1.0) < 0.5:
                zones.append({
                    "start_ms": max(0, word["start_ms"] - 200),
                    "end_ms": word["end_ms"] + 200,
                    "reason": f"protected: low confidence word '{word['word']}' ({word['confidence']:.2f})",
                    "confidence": 1.0,
                })

    return zones


def is_in_protected_zone(start_ms: int, end_ms: int, zones: list[dict]) -> tuple[bool, str]:
    """区間が保護ゾーンと重なるか確認する。"""
    for z in zones:
        overlap_start = max(start_ms, z["start_ms"])
        overlap_end = min(end_ms, z["end_ms"])
        if overlap_end > overlap_start:
            return True, z["reason"]
    return False, ""


def has_ui_event(start_ms: int, end_ms: int, ui_events: list[dict]) -> bool:
    """区間内にUIイベントがあるか確認する（speed候補に回すかどうかの判断）。"""
    for ev in ui_events:
        if ev["start_ms"] < end_ms and ev["end_ms"] > start_ms:
            return True
    return False


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────

def plan_cuts(analysis_dir: str, preset: dict, output_path: str):
    # データ読み込み
    media = load_json(f"{analysis_dir}/media.json")
    transcript = load_json(f"{analysis_dir}/transcript.json")
    vad = load_json(f"{analysis_dir}/vad.json")
    ui_events_data = load_json(f"{analysis_dir}/ui-events.json")

    duration_ms = media["duration_ms"]
    preset_cut = preset.get("cut", {})

    # 信頼度チェック
    overall_conf = transcript.get("overall_confidence", 1.0)
    conservative_mode = overall_conf < 0.7
    if conservative_mode:
        print(f"  ⚠️  書き起こし信頼度が低い ({overall_conf:.2f})。保守的モードで実行します。")

    # 保護区間を構築
    all_events = ui_events_data.get("events", [])
    protected_zones = build_protected_zones(
        all_events, transcript.get("segments", []), preset_cut
    )
    print(f"  保護区間: {len(protected_zones)}件")

    # 無音区間からカット候補を作る
    silence_regions = vad.get("silence_regions", [])
    min_cut_ms = preset_cut.get("min_silence_to_cut_ms", 500)
    sentence_pause_ms = preset_cut.get("keep_sentence_pause_ms", 180)

    segments = []
    prev_end = 0
    flags = []

    # 全区間を keep/cut に分類する
    all_boundaries = set([0, duration_ms])
    for s in silence_regions:
        all_boundaries.add(s["start_ms"])
        all_boundaries.add(s["end_ms"])
    for ev in all_events:
        all_boundaries.add(ev["start_ms"])
        all_boundaries.add(ev["end_ms"])

    boundaries = sorted(all_boundaries)

    for i in range(len(boundaries) - 1):
        seg_start = boundaries[i]
        seg_end = boundaries[i + 1]
        if seg_end <= seg_start:
            continue
        seg_dur = seg_end - seg_start

        # この区間が無音かどうか
        is_silence = any(
            s["start_ms"] <= seg_start and s["end_ms"] >= seg_end
            for s in silence_regions
        )

        # 保護区間かどうか
        protected, protect_reason = is_in_protected_zone(seg_start, seg_end, protected_zones)

        # UIイベントがあるかどうか
        has_event = has_ui_event(seg_start, seg_end, all_events)

        # 判定ロジック
        if conservative_mode:
            # 保守的モード: すべて keep
            action = "keep"
            reason = "conservative mode (low transcript confidence)"
            confidence = 0.6
        elif protected:
            action = "keep"
            reason = protect_reason
            confidence = 1.0
        elif is_silence and seg_dur >= min_cut_ms and not has_event:
            # 無音 + 十分な長さ + UIイベントなし → cut 候補
            # ただし文末の自然な間（sentence_pause_ms）は残す
            if seg_dur <= sentence_pause_ms:
                action = "keep"
                reason = f"sentence pause ({seg_dur}ms ≤ {sentence_pause_ms}ms)"
                confidence = 0.9
            else:
                action = "cut"
                reason = f"silence: {seg_dur}ms ≥ {min_cut_ms}ms, no UI event"
                confidence = 0.85
        elif is_silence and has_event:
            # 無音だがUIイベントあり → speed候補（keepとして残す）
            action = "keep"
            reason = "silence but has UI event → speed candidate"
            confidence = 0.9
        else:
            action = "keep"
            reason = "speech or active segment"
            confidence = 0.95

        segments.append({
            "start_ms": seg_start,
            "end_ms": seg_end,
            "duration_ms": seg_dur,
            "action": action,
            "reason": reason,
            "confidence": confidence,
            "protected": protected,
        })

    # 短すぎる keep セグメントを前後とマージ
    min_clip = preset_cut.get("min_kept_clip_ms", 700)
    segments = _merge_short_clips(segments, min_clip, flags)

    # 統計
    cut_total = sum(s["duration_ms"] for s in segments if s["action"] == "cut")
    keep_total = sum(s["duration_ms"] for s in segments if s["action"] == "keep")
    cut_count = sum(1 for s in segments if s["action"] == "cut")

    result = {
        "generated_from_preset": preset.get("preset_id", "unknown"),
        "total_duration_ms": duration_ms,
        "estimated_cut_ms": cut_total,
        "estimated_keep_ms": keep_total,
        "cut_ratio": round(cut_total / max(duration_ms, 1), 3),
        "conservative_mode": conservative_mode,
        "segments": segments,
        "flags": flags,
    }

    print(f"  カット: {cut_count}箇所 ({cut_total/1000:.1f}秒, {result['cut_ratio']*100:.1f}%)")
    print(f"  残し:   {keep_total/1000:.1f}秒")
    return result


def _merge_short_clips(segments: list[dict], min_ms: int, flags: list) -> list[dict]:
    """min_ms 未満の keep クリップを前後の keep に結合する。"""
    merged = list(segments)
    changed = True
    while changed:
        changed = False
        new_merged = []
        i = 0
        while i < len(merged):
            seg = merged[i]
            if (seg["action"] == "keep" and seg["duration_ms"] < min_ms and
                    i > 0 and i < len(merged) - 1):
                # 前の cut と後の cut をまとめて1つの cut にする
                if new_merged and new_merged[-1]["action"] == "cut":
                    new_merged[-1]["end_ms"] = seg["end_ms"]
                    new_merged[-1]["duration_ms"] += seg["duration_ms"]
                    new_merged[-1]["reason"] += f" [merged short clip {seg['duration_ms']}ms]"
                    flags.append(f"SHORT_CLIP_MERGED: {seg['start_ms']}ms〜{seg['end_ms']}ms")
                    changed = True
                else:
                    new_merged.append(seg)
            else:
                new_merged.append(seg)
            i += 1
        merged = new_merged
    return merged


def main():
    parser = argparse.ArgumentParser(
        description="analysis/*.json からカット計画を生成する（Step 2）"
    )
    parser.add_argument("--analysis-dir", default="analysis")
    parser.add_argument("--preset", default="presets/tutorial-balanced-ja.yaml")
    parser.add_argument("--output", default="edits/cut-plan.json")
    args = parser.parse_args()

    print("\n✂️  カット計画生成中...")
    preset = load_preset(args.preset)
    result = plan_cuts(args.analysis_dir, preset, args.output)
    save_json(result, args.output)
    print(f"\n💡 次のステップ:")
    print(f"   python scripts/edit/plan_speed.py --preset {args.preset}")


if __name__ == "__main__":
    main()
