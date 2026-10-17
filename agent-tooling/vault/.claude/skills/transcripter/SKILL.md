---
name: transcripter
description: 自作ツール transcripter でローカル完結の文字起こし・字幕生成・PDF→Markdown・動画の内容把握（動画ダイジェスト）を行う。動画や音声の中身を知りたいとき、動画編集の下見や素材整理、YouTube 用の内容把握、字幕(SRT)作成、音声のテキスト化、講義や配信の書き起こし、PDF を Markdown にしたいときに使う。Claude は動画を直接読めないので、動画を見る手段はこのスキル。
---

# transcripter（自作ツール）

音声/動画/PDF をこの Mac の中だけで処理する。**外部へ送信しない。** 詳細は `02_note/transcripter.md`。

## いつ使うか
- **動画の中身を把握する**（編集の下見、素材整理、YouTube 用の内容把握）→ `digest`
- **音声・動画を文字にする**（講義・配信・投資メモの書き起こし）→ `transcribe`
- **字幕（SRT）を作る**（DaVinci Resolve 用）→ `transcribe --format srt`
- **PDF を Markdown にする** → `pdf`

外部の動画理解サービス（Gemini API など）へ送る前に、まずこれで足りるか確認する。
**講義動画など共有禁止の素材は、ローカル処理のみ。**

## 実行（すべて `~/Documents/transcripter` で）
```bash
cd ~/Documents/transcripter
# 動画の内容把握: <動画名>_digest/ に digest.md, sheet_NN.jpg, frames/, <動画名>.json
uv run transcripter digest <動画> --interval 10 --vocab "固有名詞,地名"
uv run transcripter digest <動画> --no-transcribe --interval 5   # 静止画だけ（速い）

# 文字起こし
uv run transcripter transcribe <音声or動画> --format txt,json --vad --output <出力先>
# 字幕（SRT）＋確認プレビュー
uv run transcripter transcribe <動画> --format srt --vad --preview
# PDF → Markdown
uv run transcripter pdf <PDF> --output <出力先>
```

## digest の読み方
1. `digest.md` を読む（長さ・解像度・章ごとの静止画パスと発話）。
2. 全体像は `sheet_NN.jpg`（コンタクトシート）を **1枚** 開いて把握する。
3. 気になる区間だけ `frames/f_XXXXX.jpg` を開く。動画全体を1コマずつ開かない（トークンの無駄）。

## 置き場所のルール
- 文字起こしテキスト: 内容の領域へ。**投資系は `09_investment/transcripts/<シリーズ>/`**。
- 音声・動画などの重いファイルは**保管庫に入れない**（`~/Documents/transcripter-media/`、素材は `~/Movies/`）。
- 機微な PDF（医療データなど）は該当領域の `documents/` へ。ツールのリポジトリに置かない。
- `*_digest/` は人物の顔を含みうる。保管庫や公開先へ置かない。

## 注意
- CPU で動く。長尺は時間がかかる。固有名詞は `--vocab` でヒントを渡し、出力後に必ず確認する。
- ツール自体の改造は `~/Documents/transcripter/` で行い、`pytest` と `ruff` を通してコミットする。
- DaVinci Resolve 無料版では SRT を手動取り込み（Python スクリプトは Studio 専用になった）。
