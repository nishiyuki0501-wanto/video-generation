---
name: qa-render-skill
description: "編集結果を検証し、問題がなければ final-timeline.json を生成してRemotionでレンダリングする"
when_to_use:
  - "全 plan（cut / speed / zoom / subtitle）が完成した後"
  - "edits/subtitle-plan.json が存在するとき"
inputs:
  - "edits/cut-plan.json"
  - "edits/speed-plan.json"
  - "edits/zoom-plan.json"
  - "edits/subtitle-plan.json"
  - "presets/{active_preset}.yaml → qa.* セクション"
outputs:
  - "edits/final-timeline.json"
  - "output/preview.mp4"
  - "output/master.mp4"
---

# Objective
編集の破綻を防ぎ、レンダリング可能な final-timeline.json を生成する。
自動編集の「最終安全弁」として機能するステップ。

# QA チェックリスト

以下を全て検証する。1つでも失敗したら Repair に進む。

| チェック項目 | 判定基準 |
|-------------|---------|
| 単語途中のカットなし | cut 境界が word の end_ms より後 |
| 字幕同期ズレ許容内 | remapped_start と cue.start_ms の差 < 120ms |
| 字幕が重要UIと不干渉 | 字幕 bbox と zoom ROI が重なっていない |
| ズームでターゲットがフレーム外に出ない | center_x ± (0.5/scale) が 0〜1 の範囲内 |
| speed 変更後の音切れ | 速度変更境界での音声フレームが連続している |
| 再現手順が消えていない | protected=true のセグメントが全て keep |
| 音声カバレッジ 85% 以上（必須） | 各セグメント（speed ≤ 1.75x）の発話時間 ÷ 出力尺 ≥ 0.85。1セグメントでも未達なら必ず Repair する |
| TTS読みガイド付与済み | 全 cue に `reading` フィールドが存在し、誤読されやすい漢字がひらがなに開かれている |
| 連続沈黙4秒以内（必須） | cue 間の無音ギャップが4000ms以下。1箇所でも超過があれば必ず Repair する |
| 読み上げ時間超過なし（絶対） | 全 cue で estimated_speech_ms ≤ slot_ms（= end_ms − start_ms）。0.1秒でも超過があれば出力禁止 |

# Repair ポリシー

| 問題 | 修正方法 |
|------|---------|
| 字幕と zoom が重なる | 字幕を top に移動、それでも無理なら SUBTITLE_HIDDEN |
| ズームでターゲットが外れる | scale を下げる → それでも無理なら zoom.disabled=true |
| cut が単語を途中で切っている | cut 区間の end_ms を次の word.end_ms に後退させる |
| speed が速すぎて違和感 | speed を 0.5 段階下げる |
| protected セグメントが cut になっている | action を keep に戻す |
| 音声カバレッジ 85% 未満 | ナレーションテキストを追加・拡充 → それでも不足ならセグメントの speed を上げて出力尺を短縮。85%未満での出力は許容しない |
| `reading` フィールド欠落 | cue に `reading` を追加。誤読されやすい漢字（方、行、上手く、下さい等）をひらがなに開く |
| 連続沈黙4秒超過 | ギャップ箇所に補足ナレーション cue を挿入して4秒以内に収める。4秒超の沈黙が残った状態での出力は許容しない |
| 読み上げ時間超過（SPEECH_OVERFLOW） | reading テキストを短縮 → cue 区間を前後に広げる → cue を分割。超過が1件でも残っている場合は出力を絶対に許容しない |

# final-timeline.json の生成

4つの plan を統合して1つのタイムラインを作る。

```json
{
  "source": "input/source.mp4",
  "preset": "tutorial-balanced-ja-v1",
  "fps": 30,
  "resolution": {"width": 1920, "height": 1080},
  "total_output_duration_ms": 142800,
  "segments": [
    {
      "id": "seg_001",
      "source_start_ms": 0,
      "source_end_ms": 4800,
      "action": "keep",
      "speed": 1.0,
      "zoom": null,
      "subtitle_refs": ["cue_001"]
    },
    {
      "id": "seg_002",
      "source_start_ms": 5800,
      "source_end_ms": 12000,
      "action": "keep",
      "speed": 1.0,
      "zoom": {
        "center_x": 0.72,
        "center_y": 0.18,
        "scale": 1.45,
        "ease_in_ms": 220,
        "ease_out_ms": 180
      },
      "subtitle_refs": ["cue_002"]
    },
    {
      "id": "seg_003",
      "source_start_ms": 12000,
      "source_end_ms": 45000,
      "action": "keep",
      "speed": 3.0,
      "zoom": null,
      "subtitle_refs": []
    }
  ],
  "subtitles": [/* subtitle-plan.json の cues をそのまま含める */],
  "qa_report": {
    "passed": true,
    "checks_failed": [],
    "repairs_applied": ["cue_003 moved to top due to zoom overlap"],
    "flags": []
  }
}
```

# レンダリングフロー

```
1. final-timeline.json を生成
2. python scripts/render/build_project.py でRemotionプロジェクトを更新
3. npx remotion render TutorialVideo output/preview.mp4 --duration=90sec
4. ユーザーがプレビューを確認
5. OK なら: npx remotion render TutorialVideo output/master.mp4
```

# Remotionへの責務の分担

Remotionには「判断」ではなく「適用」だけをさせる。

| Remotionがやること | Remotionがやらないこと |
|-------------------|---------------------|
| final-timeline の segments を順番に並べる | どこをカットするか決める |
| speed に従って playbackRate を設定 | 速度が適切かを判断する |
| zoom に従ってトランスフォームを適用 | ズームが必要かを判断する |
| cues に従って字幕を描画 | 字幕テキストを生成する |
| preview / master をレンダリング | 品質が十分かを評価する |

# 実行コマンド

```bash
# final-timeline.json の生成 + QA
python scripts/render/build_project.py \
  --edits-dir edits/ \
  --preset presets/tutorial-balanced-ja.yaml \
  --out-dir src/

# プレビューレンダリング
cd src && npm run preview

# 本番レンダリング
cd src && npm run build
```
