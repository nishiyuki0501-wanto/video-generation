# 04: VOICEVOX Docker セットアップ・話者選択

## 起動手順

```bash
# イメージ取得（初回のみ・約1GBなので時間がかかることをユーザーに伝える）
docker pull voicevox/voicevox_engine:cpu-ubuntu20.04-latest

# エンジン起動
docker run -d --name voicevox_engine \
  -p 50021:50021 \
  voicevox/voicevox_engine:cpu-ubuntu20.04-latest
# ※ --host オプションは絶対に付けない（エラーになる）
# ※ --rm は付けない（ログ確認のため）

# 起動確認（数秒待ってから）
curl http://localhost:50021/version

# 既に起動しているか確認
docker ps | grep voicevox
```

## トラブルシューティング

```bash
# ログ確認
docker logs voicevox_engine
# 再起動
docker rm -f voicevox_engine
docker run -d --name voicevox_engine -p 50021:50021 voicevox/voicevox_engine:cpu-ubuntu20.04-latest
```

## テスト音声生成・話者選択

複数の話者IDでテスト音声を生成し、ユーザーに聴かせて選ばせる。

```python
import requests

VOICEVOX_URL = "http://localhost:50021"
TEST_TEXT = "こんにちは。AIナレーションのテストです。"

def generate_test(speaker_id, output_path):
    r = requests.post(f"{VOICEVOX_URL}/audio_query",
                      params={"text": TEST_TEXT, "speaker": speaker_id}, timeout=30)
    r.raise_for_status()
    r2 = requests.post(f"{VOICEVOX_URL}/synthesis",
                       params={"speaker": speaker_id},
                       json=r.json(),
                       headers={"Content-Type": "application/json"}, timeout=60)
    r2.raise_for_status()
    with open(output_path, "wb") as f:
        f.write(r2.content)
    print(f"Generated: {output_path}")

# テスト生成（主要な話者）
generate_test(2,  "test_四国めたん_ノーマル.wav")
generate_test(3,  "test_ずんだもん_ノーマル.wav")
generate_test(8,  "test_春日部つむぎ_ノーマル.wav")
generate_test(11, "test_玄野武宏_ノーマル.wav")
generate_test(13, "test_青山龍星_ノーマル.wav")
```

## 代表的な話者ID

| ID | 名前 | スタイル |
|----|------|---------|
| 2 | 四国めたん | ノーマル |
| 3 | ずんだもん | ノーマル |
| 8 | 春日部つむぎ | ノーマル |
| 11 | 玄野武宏 | ノーマル |
| 13 | 青山龍星 | ノーマル |
| 14 | 冥鳴ひまり | ノーマル |

ユーザーに `open test_*.wav` でファイルを開かせ、好みの声を選んでもらう。
