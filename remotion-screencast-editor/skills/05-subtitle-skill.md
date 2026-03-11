---
name: subtitle-skill
description: "最終タイムラインに同期した日本語字幕を生成し、表示ルールを適用する"
when_to_use:
  - "cut / speed / zoom の全 plan 完了後"
  - "edits/zoom-plan.json が存在するとき（＝3つの plan がすべて揃っているとき）"
inputs:
  - "analysis/transcript.json"
  - "analysis/ui-events.json"
  - "analysis/ocr.json（存在する場合）"
  - "edits/cut-plan.json"
  - "edits/speed-plan.json"
  - "edits/zoom-plan.json"
  - "presets/{active_preset}.yaml → subtitles.* セクション"
outputs:
  - "edits/subtitle-plan.json"
---

# Objective
読みやすく、操作の邪魔にならない字幕を生成する。
**字幕は最後。カット・速度変更後の時間軸でしか正確なタイミングを出せない。**

# 音声スクリプトカバレッジ（85%ルール）

各セグメントにおいて、音声スクリプトの発話時間がそのセグメントの出力尺の **85% 以上** を**必ず**カバーすること。これは絶対に下回ってはならない品質基準。沈黙が多い動画はプロの解説動画として成立しない。85%未満のセグメントが1つでもあれば、ナレーション追加や速度調整で必ず解消してから出力する。

**チェックタイミング：** 字幕 cues の生成後、出力前に全セグメントのカバレッジを算出する。

```python
def check_coverage(segment_start_ms, segment_end_ms, cues):
    """
    セグメント内の字幕カバレッジを算出する。
    85% 未満のセグメントは LOW_NARRATION_COVERAGE フラグを立てる。
    """
    segment_duration = segment_end_ms - segment_start_ms
    if segment_duration <= 0:
        return 1.0
    speech_ms = 0
    for cue in cues:
        overlap_start = max(cue.start_ms, segment_start_ms)
        overlap_end = min(cue.end_ms, segment_end_ms)
        if overlap_end > overlap_start:
            speech_ms += overlap_end - overlap_start
    return speech_ms / segment_duration
```

**未達時の対応（優先順）：**
1. セグメント内の操作や画面の内容に基づいてナレーションテキストを追加・拡充し、発話時間を増やす
2. それでも不足する場合は `LOW_NARRATION_COVERAGE` フラグを立ててQAスキルに判断を委ねる

**対象外：** speed > 1.75x の早送り区間やミュート区間はこのチェックの適用外とする。

# 連続沈黙の上限（4秒ルール）

**cue と cue の間の無音ギャップは最大4秒以内。これは例外なく厳守する絶対ルール。**

85%カバレッジを満たしていても、4秒を超える沈黙が1箇所でもあると視聴者は「動画が止まった」「音声トラブル」と感じる。沈黙は短く分散させ、1箇所に集中させてはならない。

**チェックタイミング：** 字幕 cues の生成後、出力前に全 cue 間のギャップを走査する。

```python
MAX_SILENCE_MS = 4000  # 4秒

def find_long_silences(cues, segment_start_ms, segment_end_ms):
    """
    cue 間のギャップが 4秒を超える箇所を検出する。
    検出された箇所には EXCESSIVE_SILENCE フラグを立てる。
    """
    violations = []
    sorted_cues = sorted(cues, key=lambda c: c.start_ms)

    # セグメント開始〜最初の cue
    if sorted_cues and sorted_cues[0].start_ms - segment_start_ms > MAX_SILENCE_MS:
        violations.append({
            "gap_start_ms": segment_start_ms,
            "gap_end_ms": sorted_cues[0].start_ms,
            "duration_ms": sorted_cues[0].start_ms - segment_start_ms
        })

    # cue 間のギャップ
    for i in range(len(sorted_cues) - 1):
        gap = sorted_cues[i + 1].start_ms - sorted_cues[i].end_ms
        if gap > MAX_SILENCE_MS:
            violations.append({
                "gap_start_ms": sorted_cues[i].end_ms,
                "gap_end_ms": sorted_cues[i + 1].start_ms,
                "duration_ms": gap
            })

    # 最後の cue〜セグメント終了
    if sorted_cues and segment_end_ms - sorted_cues[-1].end_ms > MAX_SILENCE_MS:
        violations.append({
            "gap_start_ms": sorted_cues[-1].end_ms,
            "gap_end_ms": segment_end_ms,
            "duration_ms": segment_end_ms - sorted_cues[-1].end_ms
        })

    return violations
```

**違反時の対応（必須）：**
1. ギャップ部分に操作の補足説明・画面の状況説明などのナレーションを挿入する cue を新規作成する
2. 4秒以内に収まるまでナレーションを追加し続ける
3. `EXCESSIVE_SILENCE` フラグが1つでも残っている場合は出力しない

**対象外：** speed > 1.75x の早送り区間やミュート区間はこのチェックの適用外とする。

# TTS向け漢字読みガイド（振り仮名）

VOICEVOX等のTTSエンジンは漢字の読みを頻繁に誤る。たとえば「多くの方（かた）」を「おおくのほう」と読んだり、「行（ぎょう）」を「い」と読んだりする。これを防ぐため、字幕テキストには `reading` フィールドを付与し、TTS用の読みガナ付きテキストを生成する。

**`reading` フィールドの生成ルール：**

1. 漢字の読みが文脈によって変わる語（多義語・同形異音語）には必ず読みガナを付ける
2. `reading` フィールドでは、誤読されやすい漢字をひらがなに開くか、括弧で読みを補う
3. 専門用語・固有名詞で一般的でない読みをするものは常にひらがなに開く

**誤読されやすい漢字の例（必ず `reading` で対処する）：**

| 漢字表記 | 誤読例 | 正しい読み | `reading` での表記 |
|---------|--------|-----------|-------------------|
| 方（かた） | ほう | かた | 「かた」とひらがなに開く |
| 行う | おこなう/いく | 文脈による | 文脈に合わせてひらがなに開く |
| 上手く | じょうずく | うまく | 「うまく」とひらがなに開く |
| 下さい | ください/くだされ | ください | 「ください」とひらがなに開く |
| 今日 | きょう/こんにち | 文脈による | 文脈に合わせて使い分ける |
| 一人 | ひとり/いちにん | 文脈による | 文脈に合わせてひらがなに開く |
| 何 | なに/なん | 文脈による | 文脈に合わせて使い分ける |
| 生 | せい/なま/き | 文脈による | 文脈に合わせてひらがなに開く |

**原則：** 迷ったらひらがなに開く。TTSの誤読は視聴体験を大きく損なうため、過剰に開いてでも正しく読ませることを優先する。

# 時間軸の再マッピング

カット・速度変更によって元動画の時間軸が変化している。
transcript の元タイムスタンプを「編集後タイムライン」の時間軸に変換する。

```python
def remap_time(original_ms: int, cut_plan, speed_plan) -> int:
    """
    元動画のタイムスタンプを、カット・速度変更後の出力タイムスタンプに変換する。
    cut された区間は除外し、speed が変わった区間は除算で圧縮する。
    """
    output_ms = 0
    for segment in cut_plan.segments:
        if segment.action == "cut":
            if original_ms > segment.end_ms:
                pass  # cut 分は output に加算しない
        elif segment.action == "keep":
            speed = get_speed_for_range(segment.start_ms, segment.end_ms, speed_plan)
            if original_ms <= segment.end_ms:
                delta = original_ms - segment.start_ms
                output_ms += delta / speed
                return int(output_ms)
            else:
                output_ms += (segment.end_ms - segment.start_ms) / speed
    return int(output_ms)
```

# 字幕分割ルール

1. 意味の切れ目（句読点、接続詞の前）で分割する
2. 1行 max_chars_per_line を超えたら改行
3. max_lines を超えたら次の字幕に送る
4. 1字幕が min_caption_duration_ms 未満なら前後とマージする
5. 1字幕が max_caption_duration_ms を超えたら強制分割

**分割してはいけない単語：**
- custom_terms に含まれるすべての用語
- コマンド（`npm install` など）
- パス（`/usr/local/bin` など）
- ショートカットキー（`Cmd+S` など）

# UIとの干渉チェック

字幕が zoom 対象エリアと重なる場合：
1. 字幕を上部に移動する（`position: top`）
2. それでも重なる場合は行数を減らして縮小
3. どうしても無理な場合は字幕を一時非表示にして `SUBTITLE_HIDDEN` フラグを立てる

# ハイライトの対象

以下は `highlights` に含めて強調表示する：
- ショートカットキー（`Ctrl+C`、`Cmd+K` など）
- CLIコマンド（`git commit`、`npm run dev` など）
- ファイルパス・URL
- custom_terms に含まれる用語

# 読み上げ時間の超過禁止（絶対ルール）

**各 cue の読み上げ推定時間は、その cue に割り当てられた区間（end_ms − start_ms）を 0.1秒たりとも超えてはならない。**

超過すると次の cue の音声と重なり、動画全体が破綻する。短い分には許容するが、超過は一切許容しない。これは全ルールの中で最も厳格な制約として扱う。

**推定読み上げ時間の算出：**
- 日本語ナレーション：1文字あたり約 150ms（句読点・間を含む）
- 英語・コマンド部分：1単語あたり約 400ms
- 数字・記号：1文字あたり約 200ms

```python
def estimate_speech_duration_ms(reading_text: str) -> int:
    """
    reading テキストから推定読み上げ時間を算出する。
    日本語文字=150ms/文字、英単語=400ms/語、数字記号=200ms/文字
    """
    import re
    total_ms = 0
    # 英単語（連続する半角英字）
    en_words = re.findall(r'[a-zA-Z]+', reading_text)
    total_ms += len(en_words) * 400
    # 数字・記号（半角）
    symbols = re.findall(r'[0-9!@#$%^&*()_+=\-\[\]{};:\'",.<>?/\\|`~]', reading_text)
    total_ms += len(symbols) * 200
    # 日本語文字（ひらがな・カタカナ・漢字）
    ja_chars = re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', reading_text)
    total_ms += len(ja_chars) * 150
    return total_ms

def validate_cue_duration(cue) -> dict:
    """
    cue の読み上げ推定時間が割り当て区間を超過していないか検証する。
    超過している場合は SPEECH_OVERFLOW フラグを立てる。
    """
    slot_ms = cue.end_ms - cue.start_ms
    estimated_ms = estimate_speech_duration_ms(cue.reading)
    overflow_ms = estimated_ms - slot_ms
    return {
        "cue_id": cue.id,
        "slot_ms": slot_ms,
        "estimated_ms": estimated_ms,
        "overflow_ms": max(0, overflow_ms),
        "passed": overflow_ms <= 0
    }
```

**超過が検出された場合の対応（優先順）：**
1. reading テキストを短縮する（冗長な表現を削る、言い換える）
2. cue の区間を前後に広げる（隣接 cue との間にスペースがある場合）
3. cue を分割して2つの区間に分ける

**最終検証（出力直前に必ず実行）：**
全 cue に対して `validate_cue_duration()` を実行し、`SPEECH_OVERFLOW` フラグが1つでも存在する場合は出力を中止する。この検証は subtitle-plan.json を書き出す直前の最後のステップとして必ず行う。

# 出力形式

```json
{
  "generated_from_preset": "tutorial-balanced-ja-v1",
  "cues": [
    {
      "id": "cue_001",
      "start_ms": 1200,
      "end_ms": 4800,
      "text": "多くの方が使う設定画面を開きます",
      "reading": "おおくのかたがつかう設定画面をひらきます",
      "estimated_speech_ms": 2700,
      "slot_ms": 3600,
      "lines": ["多くの方が使う設定画面を開きます"],
      "highlights": [],
      "position": "bottom",
      "confidence": 0.94,
      "flags": []
    },
    {
      "id": "cue_002",
      "start_ms": 5100,
      "end_ms": 8400,
      "text": "Cmd+K で検索できます",
      "reading": "コマンドケー で検索できます",
      "estimated_speech_ms": 2050,
      "slot_ms": 3300,
      "lines": ["Cmd+K で検索できます"],
      "highlights": [{"text": "Cmd+K", "color": "keyword_color"}],
      "position": "bottom",
      "confidence": 0.91,
      "flags": []
    },
    {
      "id": "cue_003",
      "start_ms": 22000,
      "end_ms": 24800,
      "text": "npm run dev を実行します",
      "reading": "エヌピーエム ラン デヴ を実行します",
      "estimated_speech_ms": 2400,
      "slot_ms": 2800,
      "lines": ["npm run dev を実行します"],
      "highlights": [{"text": "npm run dev", "color": "keyword_color"}],
      "position": "top",
      "confidence": 0.89,
      "flags": ["MOVED_TO_TOP_DUE_TO_ZOOM_OVERLAP"]
    }
  ],
  "flags": []
}
```

# 実行コマンド

```bash
python scripts/edit/plan_subtitles.py \
  --analysis-dir analysis/ \
  --edits-dir edits/ \
  --preset presets/tutorial-balanced-ja.yaml \
  --output edits/subtitle-plan.json
```
