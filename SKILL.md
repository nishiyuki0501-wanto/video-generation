---
name: narration-video-producer
description: |
  動画ファイルをアップロードすると、Whisper文字起こし→ナレーション変換→FFmpegカット編集→VOICEVOX音声生成→最終動画合成まで全自動で行う動画ナレーション制作パイプライン。
  「動画にAIナレーションを付けたい」「動画の音声をAIナレーションに差し替えたい」「解説動画を自動生成したい」「VOICEVOXでナレーション動画を作りたい」「動画に日本語ナレーションをつけたい」「動画の元音声をTTSに置き換えたい」と言ったら必ずこのスキル。
  faster-whisper（文字起こし）+ FFmpeg（動画カット）+ VOICEVOX Docker（日本語TTS）を使う。
  narration-video-editorスキルの後工程（音声生成）も含む完全版パイプライン。
  Claude Codeで動かすことを前提とする。
---

# Narration Video Producer スキル

## 概要

動画 → Whisper文字起こし → ナレーション変換 → FFmpegカット → VOICEVOX TTS → 最終動画合成の完全自動パイプライン。

**やること：**
1. faster-whisperで動画を文字起こし（タイムスタンプ付き）
2. 話し言葉 → 丁寧な解説文ナレーションに変換（scene_duration × 5文字/秒で収まるよう調整）
3. カットプラン（cut-plan.json）を生成し不要シーンを除外
4. FFmpeg concat demuxerで高速無劣化カット結合 → master.mp4
5. 英数字・アルファベットをカタカナ読みに変換（VOICEVOX発音修正）
6. VOICEVOXをDockerで起動し、複数の声でテスト音声を生成してユーザーに選ばせる
7. 全ナレーションをVOICEVOXで個別生成・シーン尺にパディング
8. 元音声を削除してAIナレーション音声に差し替え → final.mp4

**やらないこと：**
- 有料TTS（OpenAI等）の使用（VOICEVOX=無料が前提）
- 動画の内容変更・再編集（narration-video-editorスキルが担当）

---

## ディレクトリ構造

```
video/
├── input/source.mp4              # 元動画
├── edits/
│   ├── cut-plan.json             # クリップ情報
│   └── concat-list.txt           # FFmpeg用リスト
├── narration/
│   ├── narration-script.json     # ナレーション全文
│   ├── generate_audio.py         # VOICEVOX音声生成スクリプト
│   └── audio/narration.wav       # 全セグメント結合済み
└── output/
    ├── master.mp4                 # FFmpegカット済み動画
    └── final.mp4                  # ナレーション合成済み最終動画
```

---

## 必須の処理順序

```
Step 1: transcribe     → 文字起こし
Step 2: narrate        → narration-script.json 生成（文字数制限厳守）
Step 3: cut-plan       → cut-plan.json + concat-list.txt 生成
Step 4: master-video   → FFmpeg concat → master.mp4
Step 5: phonetic-fix   → 英数字→カタカナ変換（文字数再チェック）
Step 6: voicevox-setup → Docker起動・話者テスト・選択
Step 7: generate-audio → generate_audio.py 実行 → narration.wav
Step 8: final-merge    → master.mp4 + narration.wav → final.mp4
```

詳細は `references/` フォルダを参照：

| ファイル | 役割 |
|---------|------|
| `references/01-transcribe.md` | Whisper文字起こし手順 |
| `references/02-narrate.md` | ナレーション変換ルール・文字数制限 |
| `references/03-cut-plan.md` | FFmpegカットプラン生成 |
| `references/04-voicevox.md` | VOICEVOX Dockerセットアップ・話者選択 |
| `references/05-generate-audio.md` | generate_audio.py の詳細ロジック |
| `references/06-phonetic.md` | 英数字→カタカナ変換ルール表 |

---

## スクリプト一覧

```bash
# Step 1: 文字起こし
python scripts/transcribe.py input/source.mp4

# Step 7: VOICEVOX音声生成 + 動画合成（generate_audio.pyはスキルが動的生成）
python narration/generate_audio.py
```

依存インストール：
```bash
pip install faster-whisper requests
brew install ffmpeg
docker pull voicevox/voicevox_engine:cpu-ubuntu20.04-latest
```

---

## 重要な判断ルール

1. **文字数制限を必ず守る** — `len(text) <= scene_duration_sec * 5.0`（floating point注意）
2. **アルファベットはカタカナに** — VOICEVOXはアルファベットをそのまま読む
3. **master.mp4の座標はソースと別** — narration-script.jsonのsec値≠master.mp4上の位置
4. **silenceでギャップを埋める** — ナレーション区間以外は無音で埋めて長さを合わせる
5. **元音声は完全削除** — `-map 0:v:0 -map 1:a:0` で映像のみ元動画から取る
