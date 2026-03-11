---
name: cut-skill
description: "無音・待ち時間・言い直し・価値の低い間をカットする"
when_to_use:
  - "intake-analysis 完了後"
  - "analysis/transcript.json と analysis/vad.json が存在するとき"
inputs:
  - "analysis/transcript.json"
  - "analysis/vad.json"
  - "analysis/ui-events.json"
  - "presets/{active_preset}.yaml → cut.* セクション"
outputs:
  - "edits/cut-plan.json"
---

# Objective
視聴理解を損なわずに、冗長な部分を削除する計画を作る。
**削除ではなく保持を優先。迷ったら keep にする。**

# デフォルトで keep にすること

以下は必ず残す：
- 操作手順の説明をしている発話（「ここをクリックします」「次に〜」）
- クリック・入力の前後（preset の keep_pre/post_action_ms で定義）
- 成功・失敗が分かるUI変化の瞬間
- エラーや警告が表示される場面
- 再現に必要なすべての操作ステップ
- 初出のコマンド名・設定名・メニュー名が登場する発話

# cut 候補にすること

以下が条件を満たす場合にのみ cut 候補とする：
1. preset の min_silence_to_cut_ms 以上の無音
2. かつ、その無音区間でUIイベントが発生していない
3. かつ、直前の発話の単語が完了している（文節・単語の途中でない）

```
典型的なカット対象：
- 操作前に何もしない間（ローディング以外）
- 明確な言い直しの第1回目（「えっと、あの〜」など）
- 目的に無関係な待機（マウスが止まって何もしていない）
- 説明が完全に終わった後の沈黙
```

# 保護ルール（絶対に cut しない）

```python
# 以下の区間は action = "keep" かつ protected = True
protected_zones = []

for event in ui_events:
    if event["type"] in ("click", "typing", "modal_open"):
        protected_zones.append({
            "start_ms": event["start_ms"] - preset.keep_pre_action_ms,
            "end_ms": event["end_ms"] + preset.keep_post_action_ms,
            "reason": f"UI action: {event['type']}"
        })
```

加えて：
- 単語の confidence < 0.5 の周辺 ±200ms
- transcript.overall_confidence < 0.7 の場合、全 cut を禁止

# 実行コマンド

```bash
python scripts/edit/plan_cuts.py \
  --analysis-dir analysis/ \
  --preset presets/tutorial-balanced-ja.yaml \
  --output edits/cut-plan.json
```

# 出力形式

```json
{
  "generated_from_preset": "tutorial-balanced-ja-v1",
  "total_duration_ms": 183400,
  "estimated_cut_ms": 24600,
  "segments": [
    {
      "start_ms": 0,
      "end_ms": 4800,
      "action": "keep",
      "reason": "intro speech",
      "confidence": 0.95,
      "protected": false
    },
    {
      "start_ms": 4800,
      "end_ms": 5800,
      "action": "cut",
      "reason": "silence: 1000ms, no UI event",
      "confidence": 0.88,
      "protected": false
    },
    {
      "start_ms": 5800,
      "end_ms": 7200,
      "action": "keep",
      "reason": "click event at 6100ms → protected",
      "confidence": 1.0,
      "protected": true
    }
  ],
  "flags": []
}
```

# フラグの種類

| flag | 意味 |
|------|------|
| `LOW_TRANSCRIPT_CONFIDENCE` | 書き起こし信頼度が低く cut を抑制した |
| `PROTECTED_CLICK_NEARBY` | click イベントが近いため cut を取り消した |
| `SHORT_CLIP_MERGED` | 短すぎる keep クリップを前後とマージした |
| `REVIEW_NEEDED` | 手動確認を推奨する区間あり |

# downstream への引き継ぎ

speed-skill には以下を伝える：
- keep 区間のうち UIイベントがある区間（速度変更の候補から外す参考に）
- silence_regions のうち cut せずに残したもの（speed 候補として速度変更を検討）
