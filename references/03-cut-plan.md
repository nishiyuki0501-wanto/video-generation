# 03: FFmpegカットプラン生成

narration-script.jsonのシーンに対応するクリップだけ残したcut-plan.jsonを生成し、master.mp4を作る。

## cut-plan.json フォーマット

```json
{
  "clips": [
    {
      "clip_id": 1,
      "source_start_sec": 0.0,
      "source_end_sec": 5.2,
      "keep": true,
      "narration_id": 1,
      "trim_to_sec": null
    },
    {
      "clip_id": 2,
      "source_start_sec": 5.2,
      "source_end_sec": 8.0,
      "keep": false,
      "narration_id": null,
      "trim_to_sec": null
    }
  ]
}
```

- `keep: true` のクリップのみ master.mp4 に含める
- `narration_id`: 複数クリップが同じIDを持てる（1ナレーション = 複数クリップOK）
- `trim_to_sec`: null の場合は source_end - source_start を使用

## concat-list.txt フォーマット（絶対パス必須）

```
file '/Users/xxx/Downloads/video/input/source.mp4'
inpoint 0.000
outpoint 5.200

file '/Users/xxx/Downloads/video/input/source.mp4'
inpoint 10.500
outpoint 18.300
```

## FFmpegコマンド

```bash
/opt/homebrew/bin/ffmpeg -y -f concat -safe 0 -i edits/concat-list.txt \
  -c:v copy -c:a copy output/master.mp4
```

- `-safe 0` が必要（絶対パス使用時）
- `-c:v copy -c:a copy` で無劣化高速コピー（再エンコードなし）
