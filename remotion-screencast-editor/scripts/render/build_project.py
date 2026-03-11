#!/usr/bin/env python3
"""
build_project.py
================
全 plan を統合して final-timeline.json を生成し、
Remotionプロジェクトをビルドする（Step 6）。

使い方:
  python scripts/render/build_project.py \
      --edits-dir edits/ \
      --preset presets/tutorial-balanced-ja.yaml \
      --out-dir src/
"""

import argparse
import json
import os
import sys
import yaml
from pathlib import Path


def load_json(path):
    if not os.path.exists(path):
        print(f"  ❌ 見つかりません: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(data, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_preset(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  ✅ {path}")


# ──────────────────────────────────────────────
# QA チェック
# ──────────────────────────────────────────────

def run_qa(cut_plan, speed_plan, zoom_plan, subtitle_plan, qa_preset) -> dict:
    """QAチェックを実行し、修正が必要な箇所を返す。"""
    checks_failed = []
    repairs = []

    # 1. protected セグメントが cut になっていないか
    for seg in cut_plan["segments"]:
        if seg.get("protected") and seg["action"] == "cut":
            checks_failed.append(f"protected segment was cut: {seg['start_ms']}ms")
            seg["action"] = "keep"
            repairs.append(f"reverted cut on protected segment at {seg['start_ms']}ms")

    # 2. ズームでフレームアウトしていないか
    for ev in zoom_plan.get("events", []):
        if ev.get("disabled"):
            continue
        scale = ev.get("scale", 1.0)
        cx = ev.get("center_x", 0.5)
        cy = ev.get("center_y", 0.5)
        half = 0.5 / scale
        if cx - half < 0 or cx + half > 1 or cy - half < 0 or cy + half > 1:
            checks_failed.append(
                f"zoom target out of frame at {ev['start_ms']}ms "
                f"(center: {cx:.2f},{cy:.2f}, scale: {scale})"
            )
            ev["disabled"] = True
            ev["disabled_reason"] = "QA: target would be out of frame"
            repairs.append(f"disabled zoom at {ev['start_ms']}ms (frame out)")

    # 3. 字幕とズームの干渉チェック（再確認）
    zoom_events = [ev for ev in zoom_plan.get("events", []) if not ev.get("disabled")]
    for cue in subtitle_plan.get("cues", []):
        if cue["position"] == "bottom":
            for ev in zoom_events:
                if (ev["start_ms"] < cue["end_ms"] and
                        ev["end_ms"] > cue["start_ms"] and
                        ev.get("center_y", 0.5) > 0.65):
                    if "MOVED_TO_TOP_DUE_TO_ZOOM_OVERLAP" not in cue["flags"]:
                        cue["position"] = "top"
                        cue["flags"].append("QA_MOVED_TO_TOP")
                        repairs.append(f"moved {cue['id']} to top (zoom conflict)")
                    break

    passed = len(checks_failed) == 0
    return {
        "passed": passed,
        "checks_failed": checks_failed,
        "repairs_applied": repairs,
    }


# ──────────────────────────────────────────────
# final-timeline.json の生成
# ──────────────────────────────────────────────

def build_final_timeline(cut_plan, speed_plan, zoom_plan, subtitle_plan,
                          media, preset, qa_report) -> dict:
    """4つの plan を統合して final-timeline を生成する。"""
    fps = preset.get("video", {}).get("fps", 30)
    w = preset.get("video", {}).get("width", media["width"])
    h = preset.get("video", {}).get("height", media["height"])

    output_ms = 0
    segments = []

    for seg in sorted(cut_plan["segments"], key=lambda s: s["start_ms"]):
        if seg["action"] == "cut":
            continue

        seg_start = seg["start_ms"]
        seg_end = seg["end_ms"]

        # 速度を取得
        speed = 1.0
        for sp in speed_plan["segments"]:
            if sp["start_ms"] <= seg_start and sp["end_ms"] >= seg_end:
                speed = sp["speed"]
                break
        mute_audio = speed > preset.get("speed", {}).get("mute_audio_above_speed", 1.75)

        # ズームを取得（このセグメントに重なる最初の有効なズーム）
        zoom = None
        for ev in zoom_plan.get("events", []):
            if ev.get("disabled"):
                continue
            if ev["start_ms"] < seg_end and ev["end_ms"] > seg_start:
                zoom = {
                    "center_x": ev["center_x"],
                    "center_y": ev["center_y"],
                    "scale": ev["scale"],
                    "ease_in_ms": ev.get("ease_in_ms", 220),
                    "ease_out_ms": ev.get("ease_out_ms", 180),
                }
                break

        # 字幕を取得（このセグメントに重なるもの）
        out_dur = (seg_end - seg_start) / speed
        output_seg_start = output_ms

        subtitle_refs = [
            cue["id"] for cue in subtitle_plan.get("cues", [])
            if (cue["start_ms"] >= output_seg_start and
                cue["start_ms"] < output_seg_start + out_dur)
        ]

        segments.append({
            "id": f"seg_{len(segments)+1:04d}",
            "source_start_ms": seg_start,
            "source_end_ms": seg_end,
            "output_start_ms": int(output_ms),
            "output_end_ms": int(output_ms + out_dur),
            "action": "keep",
            "speed": speed,
            "mute_audio": mute_audio,
            "zoom": zoom,
            "subtitle_refs": subtitle_refs,
        })

        output_ms += out_dur

    total_output_ms = int(output_ms)

    return {
        "source": media["source_path"],
        "preset": preset.get("preset_id", "unknown"),
        "fps": fps,
        "resolution": {"width": w, "height": h},
        "total_output_duration_ms": total_output_ms,
        "total_output_frames": int(total_output_ms / 1000 * fps),
        "segments": segments,
        "subtitles": subtitle_plan.get("cues", []),
        "subtitle_style": subtitle_plan.get("style", {}),
        "qa_report": qa_report,
    }


# ──────────────────────────────────────────────
# Remotion プロジェクトのファイル生成
# ──────────────────────────────────────────────

def build_remotion_project(timeline: dict, out_dir: str):
    """final-timeline.json を元に Remotion の TypeScript ファイルを生成する。"""
    out = Path(out_dir)
    fps = timeline["fps"]
    w = timeline["resolution"]["width"]
    h = timeline["resolution"]["height"]
    total_frames = timeline["total_output_frames"]

    # package.json
    write(out / "package.json", json.dumps({
        "name": "tutorial-video",
        "version": "1.0.0",
        "scripts": {
            "dev": "npx remotion studio",
            "preview": "npx remotion render TutorialVideo output/preview.mp4 --props='{}' ",
            "build": "npx remotion render TutorialVideo output/master.mp4"
        },
        "dependencies": {
            "@remotion/cli": "4.0.0",
            "remotion": "4.0.0",
            "react": "18.2.0",
            "react-dom": "18.2.0"
        },
        "devDependencies": {
            "@types/react": "18.2.0",
            "typescript": "5.0.0"
        },
        "remotion": {"entryPoint": "src/Root.tsx"}
    }, ensure_ascii=False, indent=2))

    # remotion.config.ts
    write(out / "remotion.config.ts", """\
import {Config} from '@remotion/cli/config';
Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
""")

    # tsconfig.json
    write(out / "tsconfig.json", json.dumps({
        "compilerOptions": {
            "target": "ES2022", "lib": ["dom", "ES2022"],
            "module": "ES2022", "moduleResolution": "bundler",
            "jsx": "react-jsx", "strict": True, "skipLibCheck": True
        },
        "include": ["src"]
    }, indent=2))

    # final-timeline.json を public に配置（Remotionから読む）
    write(out / "public" / "final-timeline.json",
          json.dumps(timeline, ensure_ascii=False, indent=2))

    # src/Root.tsx
    write(out / "src" / "Root.tsx", f"""\
import {{Composition}} from 'remotion';
import {{TutorialVideo}} from './TutorialVideo';

export const RemotionRoot = () => {{
  return (
    <Composition
      id="TutorialVideo"
      component={{TutorialVideo}}
      durationInFrames={{{total_frames}}}
      fps={{{fps}}}
      width={{{w}}}
      height={{{h}}}
    />
  );
}};
""")

    # src/TutorialVideo.tsx — final-timeline.json を読んで合成する
    write(out / "src" / "TutorialVideo.tsx", _build_tutorial_video_tsx())

    # src/components/ 以下のコンポーネント群
    _write_components(out)

    print(f"\n  📁 プロジェクト生成完了: {out_dir}")
    print(f"  動画: {w}x{h}, {fps}fps, {total_frames}フレーム ({timeline['total_output_duration_ms']/1000:.1f}秒)")


def _build_tutorial_video_tsx() -> str:
    return """\
import React from 'react';
import {AbsoluteFill, OffthreadVideo, Sequence, staticFile,
        useCurrentFrame, useVideoConfig} from 'remotion';
import {ZoomEffect} from './components/ZoomEffect';
import {Subtitle} from './components/Subtitle';
import {ProgressBar} from './components/ProgressBar';

// final-timeline.json を読み込む
// eslint-disable-next-line @typescript-eslint/no-var-requires
const timeline = require('../public/final-timeline.json');

export const TutorialVideo: React.FC = () => {
  const {fps} = useVideoConfig();
  const segments = timeline.segments as any[];
  const cues = timeline.subtitles as any[];
  const style = timeline.subtitle_style as any;
  const frame = useCurrentFrame();
  const currentMs = (frame / fps) * 1000;

  // 現在のフレームに該当する字幕を探す
  const activeCues = cues.filter(
    (c: any) => c.start_ms <= currentMs && c.end_ms > currentMs
  );

  return (
    <AbsoluteFill style={{background: '#000'}}>
      {segments.map((seg: any) => {
        const outputStartFrame = Math.round(seg.output_start_ms / 1000 * fps);
        const durationFrames = Math.round(
          (seg.output_end_ms - seg.output_start_ms) / 1000 * fps
        );

        const videoEl = (
          <OffthreadVideo
            src={staticFile('source.mp4')}
            startFrom={Math.round(seg.source_start_ms / 1000 * fps)}
            endAt={Math.round(seg.source_end_ms / 1000 * fps)}
            playbackRate={seg.speed}
            volume={seg.mute_audio ? 0 : 1}
            style={{width: '100%', height: '100%', objectFit: 'cover'}}
          />
        );

        return (
          <Sequence
            key={seg.id}
            from={outputStartFrame}
            durationInFrames={durationFrames}
          >
            {seg.zoom ? (
              <ZoomEffect
                centerX={seg.zoom.center_x}
                centerY={seg.zoom.center_y}
                scale={seg.zoom.scale}
                easeInFrames={Math.round(seg.zoom.ease_in_ms / 1000 * fps)}
                easeOutFrames={Math.round(seg.zoom.ease_out_ms / 1000 * fps)}
                totalFrames={durationFrames}
              >
                {videoEl}
              </ZoomEffect>
            ) : videoEl}
          </Sequence>
        );
      })}

      {/* 字幕レイヤー */}
      {activeCues.map((cue: any) => (
        <Subtitle key={cue.id} cue={cue} style={style} />
      ))}

      <ProgressBar />
    </AbsoluteFill>
  );
};
"""


def _write_components(out: Path):
    """コンポーネントファイルを書き出す。"""
    comp = out / "src" / "components"

    write(comp / "ZoomEffect.tsx", """\
import React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';

type ZoomEffectProps = {
  centerX: number; centerY: number; scale: number;
  easeInFrames: number; easeOutFrames: number; totalFrames: number;
  children: React.ReactNode;
};

export const ZoomEffect: React.FC<ZoomEffectProps> = ({
  centerX, centerY, scale, easeInFrames, easeOutFrames, totalFrames, children,
}) => {
  const frame = useCurrentFrame();

  // ease in / hold / ease out
  const easeIn = interpolate(frame, [0, easeInFrames], [1, scale], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    easing: Easing.bezier(0.25, 0.46, 0.45, 0.94),
  });
  const easeOut = interpolate(
    frame, [totalFrames - easeOutFrames, totalFrames], [scale, 1],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      easing: Easing.bezier(0.55, 0.06, 0.68, 0.19) }
  );
  const currentScale = frame < easeInFrames ? easeIn
    : frame > totalFrames - easeOutFrames ? easeOut : scale;

  const tx = interpolate(currentScale, [1, scale], [0, (0.5 - centerX) * 100]);
  const ty = interpolate(currentScale, [1, scale], [0, (0.5 - centerY) * 100]);

  return (
    <div style={{width: '100%', height: '100%', overflow: 'hidden'}}>
      <div style={{
        width: '100%', height: '100%',
        transform: `scale(${currentScale}) translate(${tx}%, ${ty}%)`,
        transformOrigin: `${centerX * 100}% ${centerY * 100}%`,
      }}>
        {children}
      </div>
    </div>
  );
};
""")

    write(comp / "Subtitle.tsx", """\
import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

type Cue = {
  id: string; start_ms: number; end_ms: number;
  lines: string[]; highlights: {text: string; color: string}[];
  position: 'top' | 'bottom';
};

type StyleConfig = {
  font_family?: string; font_weight?: number; font_size?: number;
  text_color?: string; keyword_color?: string; stroke_color?: string;
  stroke_width?: number; bg_color?: string;
  padding_x?: number; padding_y?: number; border_radius?: number;
};

type SubtitleProps = { cue: Cue; style: StyleConfig };

export const Subtitle: React.FC<SubtitleProps> = ({cue, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const durationMs = cue.end_ms - cue.start_ms;
  const durationFrames = Math.round(durationMs / 1000 * fps);

  const fadeIn = interpolate(frame, [0, 4], [0, 1], {extrapolateRight: 'clamp'});
  const fadeOut = interpolate(
    frame, [durationFrames - 4, durationFrames], [1, 0],
    {extrapolateLeft: 'clamp'}
  );
  const opacity = Math.min(fadeIn, fadeOut);

  const ff = style.font_family || 'Noto Sans JP, sans-serif';
  const fw = style.font_weight || 700;
  const fs = style.font_size || 46;
  const tc = style.text_color || '#FFFFFF';
  const kc = style.keyword_color || '#7DD3FC';
  const sc = style.stroke_color || '#000000';
  const sw = style.stroke_width || 6;
  const bg = style.bg_color || 'rgba(0,0,0,0.30)';
  const px = style.padding_x || 24;
  const py = style.padding_y || 12;
  const br = style.border_radius || 12;

  const isTop = cue.position === 'top';

  return (
    <AbsoluteFill style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: isTop ? 'flex-start' : 'flex-end',
      paddingTop: isTop ? 40 : 0,
      paddingBottom: isTop ? 0 : 52,
      opacity,
      pointerEvents: 'none',
    }}>
      <div style={{
        background: bg, padding: `${py}px ${px}px`,
        borderRadius: br, maxWidth: '84%', textAlign: 'center',
      }}>
        {cue.lines.map((line, i) => (
          <div key={i} style={{
            fontFamily: ff, fontWeight: fw, fontSize: fs,
            color: tc, lineHeight: 1.3,
            textShadow: `${sw}px ${sw}px 0 ${sc}, -${sw}px -${sw}px 0 ${sc}`,
          }}>
            {renderLineWithHighlights(line, cue.highlights, kc)}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

function renderLineWithHighlights(
  line: string,
  highlights: {text: string; color: string}[],
  keywordColor: string,
): React.ReactNode[] {
  if (!highlights.length) return [line];
  const pattern = highlights.map(h => h.text.replace(/[.*+?^${}()|[\]\\\\]/g, '\\\\$&')).join('|');
  const parts = line.split(new RegExp(`(${pattern})`, 'g'));
  return parts.map((part, i) =>
    highlights.some(h => h.text === part)
      ? <span key={i} style={{color: keywordColor}}>{part}</span>
      : part
  );
}
""")

    write(comp / "ProgressBar.tsx", """\
import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';

export const ProgressBar: React.FC = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const progress = frame / durationInFrames;
  return (
    <div style={{position: 'absolute', bottom: 0, left: 0, right: 0, height: 4,
                 background: 'rgba(255,255,255,0.15)'}}>
      <div style={{height: '100%', width: `${progress * 100}%`, background: '#3B82F6'}} />
    </div>
  );
};
""")


# ──────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="全 plan を統合して final-timeline.json + Remotionプロジェクトを生成する（Step 6）"
    )
    parser.add_argument("--edits-dir", default="edits")
    parser.add_argument("--analysis-dir", default="analysis")
    parser.add_argument("--preset", default="presets/tutorial-balanced-ja.yaml")
    parser.add_argument("--out-dir", default="src")
    args = parser.parse_args()

    print("\n🎬 final-timeline.json 生成 + QA...")

    cut_plan = load_json(f"{args.edits_dir}/cut-plan.json")
    speed_plan = load_json(f"{args.edits_dir}/speed-plan.json")
    zoom_plan = load_json(f"{args.edits_dir}/zoom-plan.json")
    subtitle_plan = load_json(f"{args.edits_dir}/subtitle-plan.json")
    media = load_json(f"{args.analysis_dir}/media.json")
    preset = load_preset(args.preset)

    # QA
    qa_report = run_qa(cut_plan, speed_plan, zoom_plan, subtitle_plan, preset.get("qa", {}))
    if qa_report["checks_failed"]:
        print(f"  ⚠️  QA修正: {len(qa_report['repairs_applied'])}件")
        for r in qa_report["repairs_applied"]:
            print(f"     - {r}")
    else:
        print("  ✅ QAパス")

    # final-timeline 生成
    timeline = build_final_timeline(
        cut_plan, speed_plan, zoom_plan, subtitle_plan, media, preset, qa_report
    )
    save_json(timeline, f"{args.edits_dir}/final-timeline.json")
    print(f"  推定出力尺: {timeline['total_output_duration_ms']/1000:.1f}秒")

    # Remotion プロジェクト生成
    print("\n📁 Remotionプロジェクトを生成中...")
    build_remotion_project(timeline, args.out_dir)

    print("\n" + "=" * 60)
    print("✅ 完了！次のステップ:")
    print(f"   1. 録画ファイルを {args.out_dir}/public/source.mp4 に配置")
    print(f"   2. cd {args.out_dir} && npm install")
    print(f"   3. npm run dev      ← プレビュー確認")
    print(f"   4. npm run build    ← 本番レンダリング")


if __name__ == "__main__":
    main()
