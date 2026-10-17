# CLAUDE.md（transcripter リポジトリ）

自作のローカル完結ツール。**音声/動画の文字起こし・字幕・PDF→Markdown・動画ダイジェスト**。外部送信しない。
使い方は `README.md`、仕様は `SPEC.md`、履歴は `CHANGELOG.md`。

## このリポジトリに置くもの / 置かないもの
- **置く**: `src/` `tests/` `docs/` `scripts/` と設定・文書。**コードのみ。**
- **置かない（`.gitignore` 済み）**: 音声・動画・PDF・文字起こし結果・メモ。データの置き場は次のとおり。

| データ | 置き場 |
| --- | --- |
| 文字起こしテキスト・要約メモ（投資系） | 保管庫 `Desktop/Obsidian/09_investment/`（`transcripts/` `notes/`） |
| 音声・サンプル動画（重いもの） | `~/Documents/transcripter-media/` |
| 素材動画 | `~/Movies/` |
| 機微PDF（医療データなど） | 保管庫の該当領域（例: `health/documents/`）。**ここに置かない** |

## 開発
```bash
uv sync --extra dev --extra morph
uv run pytest && uv run ruff check src tests
```
- 依存の追加は最小限。重い依存は任意 extra にする。ローカル完結を崩さない（外部送信はオプトインのみ）。
- 動画の静止画抽出は `-ss` の位置指定（`fps` フィルタは4K素材で遅い）。
- DaVinci Resolve 21.1 以降、Python スクリプトは Studio 専用（無料版では `scripts/davinci_import_srt.py` は動かない可能性。SRT の手動取り込みは可）。

## 保管庫側の入口
AI 向けの案内は保管庫の `02_note/transcripter.md` と、保管庫の `CLAUDE.md` / `AGENTS.md` の「自作ツール」節。
