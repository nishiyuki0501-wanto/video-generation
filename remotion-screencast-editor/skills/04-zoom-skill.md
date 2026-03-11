---
name: zoom-skill
description: "重要なUI要素や小さな操作領域を自動で拡大する"
when_to_use:
  - "speed-plan.json 完了後"
  - "edits/speed-plan.json が存在するとき"
inputs:
  - "analysis/ui-events.json"
  - "analysis/ocr.json（存在する場合）"
  - "edits/cut-plan.json"
  - "edits/speed-plan.json"
  - "presets/{active_preset}.yaml → zoom.* セクション"
outputs:
  - "edits/zoom-plan.json"
---

# Objective
視認性の低いUI要素に注意を集中させる。
**ズームは諸刃の剣。使いすぎると酔う。保守的に使う。**

# ズームトリガー（これらの条件でズームを検討する）

```
優先度高：
- click が検出された bbox が画面面積の 5% 未満
- OCR で重要文言が小さく（font-size 換算 14px 未満）表示されている
- modal_open イベント → ダイアログ内にズーム

優先度中：
- cursor_pause が 2秒以上続き、bbox が小さい
- typing イベントの入力欄が細い（高さが画面の 3% 未満）
- コードの一部変更を見せたいシーン（scene_change 後に typing）

優先度低（慎重に）：
- scroll 後に特定の要素が画面内に入ってきた
```

# ズームしない条件（これらがある場合は zoom を無効化）

```
- 対象 UI が画面面積の 25% 以上 → 十分大きい
- 速度 > 2.0x の区間 → 速い映像のズームは酔いやすい
- 直前 500ms 以内に別のズームがある → 連続ズーム禁止
- bbox の confidence < 0.6 → 位置が不安定
- カーソルが高速移動中（cursor_velocity > threshold）
- 全体の文脈（画面レイアウト）が重要な場面
```

# ズームの技術的実装（Remotion）

```tsx
// ZoomEffect はカット・速度変更後の時間軸で計算する
// center_x, center_y は 0〜1 の正規化座標
const zoom = interpolate(frame, [0, ease_in_frames], [1, scale], {
  extrapolateRight: 'clamp',
  easing: Easing.bezier(0.25, 0.46, 0.45, 0.94),
});
```

ROI の計算：
```
roi_center = event.bbox の中心
roi_with_padding = bbox を roi_padding_ratio 分だけ拡張
zoom_target = roi_center（これが画面中央に来るように平行移動）
```

# 出力形式

```json
{
  "generated_from_preset": "tutorial-balanced-ja-v1",
  "events": [
    {
      "start_ms": 8200,
      "end_ms": 11500,
      "center_x": 0.72,
      "center_y": 0.18,
      "scale": 1.45,
      "reason": "click on small button (bbox area: 2.1%)",
      "confidence": 0.84,
      "ease_in_ms": 220,
      "ease_out_ms": 180,
      "disabled": false
    },
    {
      "start_ms": 32000,
      "end_ms": 38000,
      "center_x": 0.5,
      "center_y": 0.6,
      "scale": 1.28,
      "reason": "typing in input field",
      "confidence": 0.52,
      "disabled": true,
      "disabled_reason": "low confidence bbox"
    }
  ]
}
```

# 実行コマンド

```bash
python scripts/edit/plan_zoom.py \
  --analysis-dir analysis/ \
  --cut-plan edits/cut-plan.json \
  --speed-plan edits/speed-plan.json \
  --preset presets/tutorial-balanced-ja.yaml \
  --output edits/zoom-plan.json
```
