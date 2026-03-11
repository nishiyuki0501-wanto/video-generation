# 02: ナレーションスクリプト変換

文字起こし結果を話し言葉から丁寧な解説文に変換し、narration-script.jsonを生成する。

## 重要制約：TTS文字数上限

- 日本語VOICEVOX速度：**5文字/秒**
- 各ナレーションの最大文字数 = `scene_duration_sec × 5.0`
- `len(text) <= scene_duration_sec * 5.0` を**厳守**
- floating point注意：`scene_duration * 5.0 = 30.99` のとき30字が上限（31字は超過）
- 超過する場合は内容の要点を保ちつつ短縮する

## 出力フォーマット: narration-script.json

```json
{
  "narrations": [
    {
      "id": 1,
      "text": "まず設定画面を開きます。",
      "scene_start_sec": 0.0,
      "scene_end_sec": 5.2
    }
  ]
}
```

## 変換ルール

1. **話し言葉 → 丁寧な解説文**（「えーと」「あのー」などの除去）
2. **元動画の順序を維持**（内容の並び替えは禁止）
3. **1ナレーション = 1シーン**を基本とする
4. **シーンが短い場合**（3秒未満）は2文を1シーンにまとめてよい
5. **文字数チェックは必ず全件実施**してから次のステップへ

## 文字数チェックコード

```python
errors = []
for n in narrations:
    dur = n["scene_end_sec"] - n["scene_start_sec"]
    max_chars = dur * 5.0
    if len(n["text"]) > max_chars:
        errors.append(f"narr {n['id']}: {len(n['text'])}字 > {max_chars:.2f}字")
if errors:
    for e in errors:
        print(f"⚠ {e}")
else:
    print("✅ 全ナレーション文字数OK")
```
