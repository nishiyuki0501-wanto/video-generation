# 06: 英数字→カタカナ変換ルール

VOICEVOXはアルファベット・英数字をそのまま読むため、カタカナに変換する必要がある。
narration-script.jsonのtextに適用し、変換後も文字数上限を再チェックする。

## 変換テーブル

| 元の文字 | 変換後 | 注意 |
|---------|--------|------|
| ChatGPT | チャットジーピーティー | 必ず最初に変換 |
| GPT | ジーピーティー | ChatGPT変換後に残るGPTに適用 |
| OpenAI | オープンエーアイ | |
| Microsoft Word | マイクロソフトワード | Microsoftより先に変換 |
| Microsoft | マイクロソフト | |
| Google | グーグル | |
| Codex | コーデックス | |
| Web | ウェブ | |
| AI | エーアイ | 文脈により「人工知能」でも可 |
| API | エーピーアイ | |
| URL | ユーアールエル | |
| PDF | ピーディーエフ | |
| PC | ピーシー | |
| Mac | マック | |
| iPhone | アイフォン | |
| App | アップ | |
| Excel | エクセル | |
| Word | ワード | |
| YouTube | ユーチューブ | |
| Twitter | ツイッター | |
| GitHub | ギットハブ | |

## 変換後の文字数チェック（必須）

変換でカタカナが長くなるため、上限を超える場合は文章を短縮する。

例：
- `ChatGPT` (7字) → `チャットジーピーティー` (12字) = +5字
- narr 8 の例：`31字 > 30.99字` → 1字削除して解決

## 変換コード例

```python
import re

replacements = [
    ("Microsoft Word", "マイクロソフトワード"),  # 長い語を先に
    ("ChatGPT", "チャットジーピーティー"),
    ("OpenAI", "オープンエーアイ"),
    ("Microsoft", "マイクロソフト"),
    ("Google", "グーグル"),
    ("GitHub", "ギットハブ"),
    ("YouTube", "ユーチューブ"),
    ("Twitter", "ツイッター"),
    ("iPhone", "アイフォン"),
    ("Codex", "コーデックス"),
    ("Excel", "エクセル"),
    ("Word", "ワード"),
    ("App", "アップ"),
    ("Web", "ウェブ"),
    ("Mac", "マック"),
    ("PDF", "ピーディーエフ"),
    ("API", "エーピーアイ"),
    ("URL", "ユーアールエル"),
    ("GPT", "ジーピーティー"),   # ChatGPT変換後に残るGPTに適用
    (r"\bPC\b", "ピーシー"),
    (r"\bAI\b", "エーアイ"),
]

def apply_phonetic(text):
    for src, dst in replacements:
        text = re.sub(src, dst, text)
    return text
```
