---
name: speed-skill
description: "ロード待ち・反復操作・長い移動を視認可能な範囲で早送りする"
when_to_use:
  - "cut-plan.json 完了後"
  - "edits/cut-plan.json が存在するとき"
inputs:
  - "edits/cut-plan.json"
  - "analysis/transcript.json"
  - "analysis/ui-events.json"
  - "presets/{active_preset}.yaml → speed.* セクション"
outputs:
  - "edits/speed-plan.json"
---

# Objective
情報量の低い区間を短縮しつつ、必要な視覚情報は残す。
cut で削除されなかった keep 区間のみを対象とする。

# 速度カテゴリと適用基準

| 状況 | 倍率 | 判断基準 |
|------|------|---------|
| 発話中の操作説明 | 最大 1.10x | 声とUIが同期している |
| 通常UIナビゲーション | 1.25〜1.35x | マウス移動・メニュー展開 |
| 繰り返し同じ操作 | 1.35〜1.50x | 同じ動作の2回目以降 |
| タイピング実演 | 1.15〜1.25x | キーボード入力中 |
| ローディング・待機 | 3.0x | 進捗バー・スピナー表示中 |
| 長い待機（30秒以上） | 6.0x | インストール・ビルド等 |

# 速度を上げてはいけない区間

```
- エラー・警告の説明
- 設定確認ダイアログを読む場面
- OCR で小さい文字が検出された場面
- 初出の重要用語が登場する発話
- 操作が複雑で初見だと迷いやすい箇所
- 口頭説明と操作が完全に同期している箇所
- transcript の confidence が低い区間
```

# 速度切替のトランジション

speed_ramp_transition_ms の時間をかけて緩やかに速度を変化させる。
急激な速度変化は視聴者に違和感を与える。

```
speed 1.0 → 3.0 に変わるとき：
  0ms〜160ms: 1.0 → 2.0 (ランプアップ)
  160ms〜: 3.0 (定常速度)
```

# 音声の扱い

- speed > mute_audio_above_speed（デフォルト1.75x）の場合は音声をミュートまたはフェードアウト
- 発話区間は速度を上げても音声を保持（1.10x 以内なら自然に聞こえる）

# 出力形式

```json
{
  "generated_from_preset": "tutorial-balanced-ja-v1",
  "segments": [
    {
      "start_ms": 5800,
      "end_ms": 12000,
      "speed": 1.0,
      "reason": "spoken instruction with UI sync",
      "confidence": 0.92,
      "mute_audio": false
    },
    {
      "start_ms": 12000,
      "end_ms": 45000,
      "speed": 3.0,
      "reason": "loading screen: no speech, progress bar detected",
      "confidence": 0.87,
      "mute_audio": true
    }
  ]
}
```

# 実行コマンド

```bash
python scripts/edit/plan_speed.py \
  --analysis-dir analysis/ \
  --cut-plan edits/cut-plan.json \
  --preset presets/tutorial-balanced-ja.yaml \
  --output edits/speed-plan.json
```
