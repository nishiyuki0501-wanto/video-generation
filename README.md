# Narration Video Producer / Remotion Screencast Editor

画面録画をAIナレーション付きのプロ品質の解説動画に自動変換するClaudeスキル集です。

---

## 含まれるスキル

| スキル | 概要 |
|-------|------|
| **narration-video-producer** | 動画にAIナレーションを自動生成・合成するパイプライン（Whisper → VOICEVOX → FFmpeg） |
| **remotion-screencast-editor** | 画面録画をカット・速度・ズーム・字幕編集してRemotionで出力するパイプライン |

---

## インストール方法

### 方法①：Claudeデスクトップアプリ（Cowork）を使っている場合

1. このリポジトリから **`remotion-screencast-editor.skill`** をダウンロード
2. Coworkを開き、スキルファイルを**ドラッグ＆ドロップ**してインストール

```
remotion-screencast-editor.skill  ← これをダウンロードしてCoworkにドロップ
```

### 方法②：Claude Code（CLIツール）を使っている場合

リポジトリをクローンして、スキルフォルダをClaudeのスキルディレクトリに移動します。

```bash
# リポジトリをクローン
git clone https://github.com/nishiyuki0501-wanto/video-generation.git

# スキルフォルダをClaudeのスキルディレクトリにコピー
cp -r video-generation/remotion-screencast-editor ~/.claude/skills/
```

> **スキルディレクトリの場所：**
> - macOS / Linux：`~/.claude/skills/`
> - Windows：`%USERPROFILE%\.claude\skills\`

---

## 使い方

スキルをインストールしたら、Claudeに話しかけるだけで使えます。

```
input/source.mp4 の画面録画を解説動画に編集してください。
タイトル: ○○の使い方
対象視聴者: ○○を始めたばかりの初心者
```

---

## 必要な環境

スキル本体（Claude）とは別に、以下のセットアップが必要です。

- **Python 3.9+** および以下のパッケージ
  ```bash
  pip install faster-whisper ffmpeg-python opencv-python-headless numpy pillow webrtcvad
  ```
- **Node.js 18+** および Remotion
  ```bash
  npm install -g remotion
  ```
- **FFmpeg**（`ffmpeg` コマンドが使える状態）
- **VOICEVOX**（Docker で起動）
  ```bash
  docker run -d -p 50021:50021 voicevox/voicevox_engine
  ```

---

## ライセンス

MIT
