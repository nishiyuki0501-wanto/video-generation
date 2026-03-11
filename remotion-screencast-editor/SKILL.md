---
name: remotion-screencast-editor
description: |
  画面録画をRemotionでプロ品質の解説動画に自動変換するスキル。
  「解説動画を作りたい」「画面録画を編集したい」「チュートリアル動画を作りたい」
  「ズームやカット・早送りを入れたい」「Remotionで動画を作りたい」
  「スクリーンキャストを編集したい」と言ったときは必ずこのスキルを使う。
  分析→カット→速度→ズーム→字幕→QA/レンダーの6段階パイプラインで
  自律的に編集を行い、すぐ動くRemotionプロジェクトを生成する。
---

# Remotion スクリーンキャスト 自律編集スキル

## 設計思想

このスキルは**3層に分離**されている：

- **Claude** = 編集判断のオーケストレーター（何を削るか・速くするか・ズームするかを決める）
- **スクリプト（scripts/）** = 機械的な分析と中間データ生成（ffmpeg/Whisper/OpenCV）
- **Remotion** = 最終的な映像合成とレンダリングのみを担う

Remotionに「判断」はさせない。Claudeが決めた `final-timeline.json` を**適用**するだけ。

---

## ディレクトリ構造（生成されるプロジェクト）

```
project/
  CLAUDE.md                         ← 自律行動の司令塔（ユーザーが配置）
  presets/
    tutorial-balanced-ja.yaml       ← 標準プリセット
    tutorial-safe-ja.yaml
    tutorial-aggressive-ja.yaml
  input/
    source.mp4                      ← ユーザーの録画ファイル
  analysis/                         ← Step 1: 分析結果（全処理の土台）
    media.json
    transcript.json
    vad.json
    ui-events.json
    ocr.json
  edits/                            ← Step 2〜5: 編集計画
    cut-plan.json
    speed-plan.json
    zoom-plan.json
    subtitle-plan.json
    final-timeline.json             ← 全計画を統合した最終指示書
  src/                              ← Remotionプロジェクト
    Root.tsx
    TutorialVideo.tsx               ← final-timeline.json を読んで合成
    scenes/ components/
  output/
    preview.mp4
    master.mp4
```

---

## 必須の処理順序

**絶対にこの順番を守る。**

```
1. intake-analysis   → analysis/*.json
2. cut-skill         → edits/cut-plan.json
3. speed-skill       → edits/speed-plan.json
4. zoom-skill        → edits/zoom-plan.json
5. subtitle-skill    → edits/subtitle-plan.json
6. qa-render-skill   → edits/final-timeline.json → output/*.mp4
```

字幕は必ず最後。カット・速度変更後の時間軸でしかタイミングを正確に合わせられない。
ズームはカット・速度確定後のタイムラインを前提とする。

---

## 編集の優先順位（迷ったらここを参照）

1. **理解しやすさ** > テンポ
2. **再現可能性** > 演出
3. **視認性** > 見栄え

**不確実な区間は削除ではなく保持を優先する。**
判断に迷ったら保守的に編集する。これが最重要ルール。

---

## 音声スクリプトのカバレッジルール（必須）

**音声スクリプト（ナレーション）は、その区間の動画尺の 85% 以上をカバーすること。**

沈黙が長い動画は視聴体験の質が大きく下がる。各セグメントにおいて、音声スクリプトの発話時間がそのセグメントの出力尺の 85% 未満にならないようにする。これは字幕生成（Step 5）で適用し、QA（Step 6）で検証する。

**計算式：**
```
カバレッジ = セグメント内の発話時間合計 ÷ セグメントの出力尺 × 100
→ 85% 以上であること
```

**未達時の対応（優先順）：**
1. ナレーションテキストを追加・拡充して発話時間を増やす
2. それでも不足する場合はセグメントの速度を上げて出力尺を短縮する

**対象外：** 早送り区間（speed > 1.75x）やミュート区間はこのルールの適用外とする。

---

## 連続沈黙の上限ルール（必須）

**発話と発話の間の無音時間（沈黙）は最大4秒以内とすること。これは例外なく厳守する。**

85%カバレッジを満たしていても、1箇所に4秒を超える沈黙が集中すると視聴者は「動画が止まった」「音声トラブル」と感じる。沈黙は分散させ、1箇所に集中させない。

**検出と対応：**
- 字幕生成（Step 5）で cue 間のギャップを走査し、4秒超のギャップを検出する
- QA（Step 6）で最終検証し、4秒超のギャップが残っていれば必ず Repair する
- 対応方法：ギャップ部分にナレーション（補足説明・操作の要約など）を挿入する

**対象外：** 早送り区間（speed > 1.75x）やミュート区間はこのルールの適用外とする。

---

## 読み上げ時間の超過禁止（絶対ルール）

**各 cue の読み上げ推定時間が、割り当て区間（end_ms − start_ms）を 0.1秒でも超えることは絶対に禁止。**

超過すると次の cue の音声と重なり、動画全体が破綻する。短い分には許容するが、超過は一切許容しない。字幕生成（Step 5）で全 cue の推定読み上げ時間を算出・検証し、QA（Step 6）で最終確認する。超過が1件でもあれば出力を中止する。

---

## TTS向け漢字読みガイド（振り仮名）

VOICEVOX等のTTSエンジンは漢字の読みを頻繁に誤る（例：「多くの方（かた）」→「おおくのほう」）。字幕生成（Step 5）で各 cue に `reading` フィールドを付与し、誤読されやすい漢字はひらがなに開く。詳細は `skills/05-subtitle-skill.md` の「TTS向け漢字読みガイド」セクションを参照。

---

## 各スキルの詳細

各処理の詳細な判断基準・入出力契約は `skills/` フォルダを参照：

| ファイル | 役割 |
|---------|------|
| `skills/01-intake-analysis.md` | 動画・音声・UIの分析 |
| `skills/02-cut-skill.md` | カット判断 |
| `skills/03-speed-skill.md` | 早送り判断 |
| `skills/04-zoom-skill.md` | ズーム判断 |
| `skills/05-subtitle-skill.md` | 字幕生成 |
| `skills/06-qa-render-skill.md` | QA・レンダリング |

プリセットの詳細（閾値・スタイル設定）は `presets/tutorial-balanced-ja.yaml` を参照。

---

## スクリプト一覧（scripts/）

```bash
# Step 1: 動画・音声・UIを分析してanalysis/*.jsonを生成
python scripts/analysis/analyze_media.py input/source.mp4

# Step 2: cut-plan.json を生成
python scripts/edit/plan_cuts.py

# Step 3: speed-plan.json を生成
python scripts/edit/plan_speed.py

# Step 4: zoom-plan.json を生成
python scripts/edit/plan_zoom.py

# Step 5: subtitle-plan.json を生成
python scripts/edit/plan_subtitles.py

# Step 6: final-timeline.jsonを生成してRemotionプロジェクトをビルド
python scripts/render/build_project.py
```

依存インストール：
```bash
pip install opencv-python-headless faster-whisper ffmpeg-python numpy pillow webrtcvad
# Whisperモデルは初回実行時に自動ダウンロード
```

---

## 使い方（ユーザー向け）

1. 録画を `input/source.mp4` に配置
2. `python scripts/analysis/analyze_media.py input/source.mp4` を実行
3. Claudeに「分析結果を元に編集してください」と伝える
4. Claudeが各スキルに従って `edits/*.json` を生成
5. `python scripts/render/build_project.py` でRemotionプロジェクト生成
6. `cd src && npm install && npm run dev` でプレビュー

---

## Claudeへの指示テンプレート

```
input/source.mp4 の画面録画を解説動画に編集してください。
プリセット: tutorial-balanced-ja
タイトル: ○○の使い方
対象視聴者: ○○を始めたばかりの初心者
重点的に見せたい操作: ○○
```
