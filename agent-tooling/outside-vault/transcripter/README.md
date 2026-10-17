# transcripter

ローカル完結の個人用ツール。**音声/動画の文字起こし**と **PDF→Markdown 変換**を、
すべて自分のPC上で行います（音声・PDFを外部サーバへ送信しません）。

- 🎙 **transcribe** … 音声/動画 → `txt` / `json` / **字幕 `srt`・`vtt`・`ass`**（OpenAI Whisper `turbo` を faster-whisper で実行）
- 🎬 **字幕テロップ** … 動画に整形済み字幕を自動生成（reflow整形・形態素解析・焼き込みプレビュー・DaVinci Resolve 連携）
- 📄 **pdf** … PDF → `Markdown`（PyMuPDF4LLM。任意で Docling）
- 👁 **digest** … 動画を「AI が中身を把握できる形」にする（時刻付き発話＋静止画＋コンタクトシート → `digest.md`）
- 🖥 **serve** … ローカル Web UI（ドラッグ&ドロップ、任意 `--extra webui`）

> ステータス: **CLI 実装済み** — transcribe（txt/json/srt/vtt/ass）・pdf（md）・字幕テロップ（reflow／
> スタイル／焼き込みプレビュー／形態素解析／WhisperX・話者分離／ローカルGUI）。
> 字幕の設計・整形パラメータ・DaVinci Resolve 手順は
> [`docs/subtitle-telop-plan.md`](docs/subtitle-telop-plan.md) / [`docs/davinci-workflow.md`](docs/davinci-workflow.md)、
> 全体仕様は `SPEC.md`、開発の経緯・機能追加履歴は [`CHANGELOG.md`](CHANGELOG.md) を参照。

---

## 目次
- [必要環境](#必要環境)
- [インストール](#インストール)
- [使い方](#使い方)
  - [音声/動画の文字起こし（transcribe）](#音声動画の文字起こしtranscribe)
  - [PDF→Markdown（pdf）](#pdfmarkdownpdf)
- [設定ファイル](#設定ファイル)
- [対応形式](#対応形式)
- [終了コード](#終了コード)
- [仕組み・設計](#仕組み設計)
- [開発](#開発)
- [プライバシー](#プライバシー)
- [トラブルシューティング](#トラブルシューティング)

---

## 必要環境

- **Python 3.10+**
- **FFmpeg**（`transcribe` で必須。`pdf` のみなら不要）
  - macOS: `brew install ffmpeg`
  - Windows: `winget install Gyan.FFmpeg`
  - Linux: `sudo apt install ffmpeg`
- 推奨パッケージ管理: **uv**（Apple Silicon と相性良）

> 既定は Apple Silicon / CPU 運用（`device=cpu` / `compute_type=int8`）。NVIDIA GPU があれば `--device cuda` を使用可（CUDA 12 / cuDNN 9 が必要）。

---

## インストール

```bash
# uv（推奨）
uv sync
uv run transcripter --help

# 任意: 高精度PDFバックエンド Docling も入れる場合（重い）
uv sync --extra docling

# 任意: 字幕の語境界改行に日本語形態素解析（fugashi + 辞書）を使う場合
uv sync --extra morph

# 任意: 単語±50ms整列・話者分離（WhisperX/pyannote。重い・モデルDL）
uv sync --extra whisperx

# 任意: ローカル Web UI（ドラッグ&ドロップ）
uv sync --extra webui
```

pip / venv の場合:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
transcripter --help
```

> 初回の `transcribe` 実行時に Whisper `turbo` モデル（約 1.5GB）が `~/.cache/huggingface` にダウンロードされます。

---

## 使い方

トップレベルに 2 つのサブコマンドがあります。

```bash
transcripter transcribe <音声/動画...> [オプション]
transcripter pdf        <PDF...>        [オプション]
```

### 音声/動画の文字起こし（transcribe）

```bash
# 単一ファイル → txt（既定: 言語 ja、入力と同じ場所に出力）
uv run transcripter transcribe input.mp3

# 形式と出力先を指定（複数形式同時）
uv run transcripter transcribe input.mp4 --format txt,json --output ./outputs

# ディレクトリを再帰一括 + VAD（無音除去・長尺で有効）
uv run transcripter transcribe ./audios --recursive --vad

# 言語自動判定・時刻つき txt
uv run transcripter transcribe talk.m4a --language auto --timestamps

# 動画に字幕テロップ（SRT）＋焼き込み確認プレビュー（DaVinci Resolve 連携）
uv run transcripter transcribe trip.mp4 --format srt --vad --preview

# 高精度整列＋話者分離つき字幕（要 --extra whisperx ＋ HFトークン）
uv run transcripter transcribe talk.mp4 --format srt --backend whisperx --diarize --speaker-labels

# ローカル Web UI（ドラッグ&ドロップ。要 --extra webui）
uv run transcripter serve   # → http://127.0.0.1:8765
```

> 字幕テロップ（`srt`/`vtt`/`ass`）の設計・整形パラメータ・DaVinci Resolve への
> 取り込み手順は [`docs/subtitle-telop-plan.md`](docs/subtitle-telop-plan.md) と
> [`docs/davinci-workflow.md`](docs/davinci-workflow.md) を参照。

**主なオプション**

| オプション | 既定 | 説明 |
|-----------|------|------|
| `--model` | `turbo` | Whisper モデル名 |
| `--language, -l` | `ja` | 言語（`auto` で自動判定） |
| `--format, -f` | `txt` | `txt,json,srt,vtt,ass`（カンマ区切りで複数） |
| `--output, -o` | 入力と同じ | 出力先ディレクトリ |
| `--device` | `cpu` | `auto / cpu / cuda` |
| `--compute-type` | `int8` | `int8 / float16 / int8_float16 / float32` |
| `--vad / --no-vad` | off | VAD（無音除去。字幕・長尺で推奨） |
| `--timestamps` | off | txt に `[HH:MM:SS]` を付与 |
| `--preview` | off | 字幕を焼き込んだ確認用 mp4（動画のみ・既定1080p30） |
| `--sub-font / --sub-font-size / --sub-italic / --sub-position 等` | — | 字幕のフォント・サイズ・位置・スタイル（→[字幕テロップのスタイル](#字幕テロップのスタイルフォントサイズ位置イタリック)） |
| `--denoise` | off | 風切り音・ノイズ低減＋音量正規化（屋外/アクションカメラ向け・精度↑） |
| `--vocab` | — | 固有名詞ヒント（カンマ区切り。地名・人名の認識を改善） |
| `--accurate` | off | 精度優先プリセット（large-v3・VAD・条件付けOFF・ノイズ低減） |
| `--llm-correct` | off | LLMで誤変換・句読点を後補正（既定 ollama＝ローカル。外部APIは任意） |
| `--recursive, -r` | off | ディレクトリ再帰探索 |
| `--overwrite` | off | 既存出力を上書き |

字幕系（`--format srt,vtt,ass`）指定時は word 単位時刻が自動で有効になり、
読みやすい行長・表示時間・改行に整形されます（パラメータは `--help` と `docs/`）。

### 動画ダイジェスト（digest）— AI に動画の中身を把握させる

```bash
# 動画 → <動画名>_digest/ に digest.md・sheet_NN.jpg・frames/・<動画名>.json
uv run transcripter digest trip.mp4 --interval 10 --vocab "神戸,ハーバーランド"

# 静止画だけ（文字起こし省略・速い）
uv run transcripter digest trip.mp4 --no-transcribe --interval 5
```

- `digest.md` は章（`--interval` 秒ごと）ごとに、静止画のパスと、その区間に始まる発話を時刻付きで並べる。
- AI（Claude Code など）は `digest.md` を読み、全体像は `sheet_NN.jpg`（コンタクトシート）を1枚開いて把握し、
  気になる区間だけ `frames/` の静止画を開く。**外部送信なし**（すべてローカル）。
- 4K/120fps の素材でも速いように、静止画は位置指定（`-ss`）で1枚ずつ抜く。

#### 認識精度を上げる（段階的）

```bash
# ① 前処理＋語彙ヒント（ローカル・低コスト。屋外音声・固有名詞に効く）
uv run transcripter transcribe trip.mp4 --format srt --vad \
    --denoise --vocab "神戸,ハーバーランド,メリケンパーク"

# ② 精度優先プリセット（large-v3 に切替。CPUでは遅い）
uv run transcripter transcribe trip.mp4 --format srt --accurate

# ③ LLM後補正（既定は【ローカル Ollama】＝外部送信なし。要 Ollama 導入）
uv run transcripter transcribe trip.mp4 --format srt --llm-correct
#   ollama を入れて日本語モデルを取得: ollama pull qwen2.5:7b

# ④ 外部API後補正（最高精度・★オプトイン＝音声由来テキストが外部へ・課金）
uv run transcripter transcribe trip.mp4 --format srt \
    --llm-correct --llm-backend anthropic   # 要 ANTHROPIC_API_KEY
```

> LLM後補正は「言い換え・要約はせず誤変換・句読点だけを直す」制約で本文のみ補正し、
> タイミング（word時刻・字幕区間）は変更しません。**既定はローカル完結**（Ollama）、
> 外部API（`--llm-backend anthropic`）は明示オプトイン時のみ音声由来テキストを送信します。

#### 字幕テロップのスタイル（フォント・サイズ・位置・イタリック）

**既定のスタイル**（`--format srt,vtt,ass` / `--preview` 生成時に適用）

| 項目 | 既定値 | 補足 |
|------|--------|------|
| フォント | `Noto Sans JP` | 見た目は焼き込み(ASS)・プレビューに反映。**PCに入っているフォント名**を指定（macOSは `Hiragino Sans W6` 等が確実） |
| 太字 | ON | |
| イタリック | OFF | 和文は疑似オブリーク（傾け）で表現 |
| フォントサイズ | フレーム高の **4.0%** | 1080pなら約43px |
| 文字色 / 縁取り / 帯 | 白 / **なし** / **なし** | 明るい背景では縁 or 帯を推奨 |
| 位置 / 配置 | 下 / 中央 | 下マージン10% |
| 1字幕の行数 / 文字数 | **1行** / 最大32字 | 句点(。！？)では必ず改字幕。一続きの文は1枚にまとめる |

**変更方法（CLI）**

```bash
# イタリック体にする
uv run transcripter transcribe v.mp4 --format srt --preview --sub-italic

# フォントサイズを指定（フレーム高に対する%。小さめ=3.5、大きめ=6.0 など）
uv run transcripter transcribe v.mp4 --format srt --preview --sub-font-size 3.5

# 位置を上にする（bottom / top）
uv run transcripter transcribe v.mp4 --format srt --preview --sub-position top

# フォントを変える（PCにインストール済みの名前）
uv run transcripter transcribe v.mp4 --format srt --preview --sub-font "Hiragino Maru Gothic ProN"

# まとめて: 帯つきプリセット＋位置＋サイズ
uv run transcripter transcribe v.mp4 --format srt --preview \
    --sub-preset box --sub-position bottom --sub-font-size 4.5
```

| オプション | 既定 | 説明 |
|-----------|------|------|
| `--sub-font` | `Noto Sans JP` | フォント名（インストール済みのもの） |
| `--sub-font-size` | `4.0` | フォントサイズ（フレーム高に対する%） |
| `--sub-italic / --no-sub-italic` | off | 斜体（和文は疑似オブリーク） |
| `--sub-position` | `bottom` | 字幕位置 `bottom` / `top` |
| `--sub-preset` | —（縁なし） | `outline`（白+黒縁）/ `box`（帯）/ `cinema`。無指定なら上表の既定 |
| `--sub-box / --no-sub-box` | off | 帯（背景）の有無 |
| `--sub-box-opacity` | `70` | 帯の不透明度%（100=不透明） |

> 設定ファイル（`config.toml` の `[subtitle.style]`）でも同じ項目を既定として保存できます
> （`config.example.toml` 参照）。DaVinci Resolve では SRT に見た目情報が乗らないため、
> フォント・サイズ・位置は Resolve のインスペクタ側で設定します → [`docs/davinci-workflow.md`](docs/davinci-workflow.md)。

### PDF→Markdown（pdf）

```bash
# 単一ファイル → 同じ場所に .md
uv run transcripter pdf report.pdf

# 出力先を指定
uv run transcripter pdf report.pdf --output ./outputs

# 複数 / ディレクトリ一括
uv run transcripter pdf ./docs --recursive

# 高精度バックエンド（スキャンPDF・複雑な表向け。要 --extra docling）
uv run transcripter pdf scanned.pdf --backend docling
```

**主なオプション**

| オプション | 既定 | 説明 |
|-----------|------|------|
| `--output, -o` | 入力と同じ | 出力先ディレクトリ |
| `--backend, -b` | `pymupdf4llm` | `pymupdf4llm`（軽量）/ `docling`（高精度・要追加インストール） |
| `--recursive, -r` | off | ディレクトリ再帰探索 |
| `--overwrite` | off | 既存 `.md` を上書き |

**バックエンドの選び方**

| 用途 | 推奨 |
|------|------|
| デジタルPDF（テキスト埋め込み・大多数） | **pymupdf4llm**（既定・速い・軽い） |
| スキャン画像PDF / 複雑な結合セル表 | **docling**（`--extra docling`。重い・モデルDLあり） |

> 検証では、テキスト層を持つ日本語PDF（表中心）は pymupdf4llm が速度・精度・日本語の質で最良でした。Docling はテキスト層を OCR で作り直すため、デジタルPDFでは日本語が崩れやすく低速です。詳細は `SPEC.md`。

---

## 設定ファイル

`config.example.toml` を `config.toml` にコピーして既定を変更できます。
カレントに `config.toml` があれば自動で読み込みます（`--config` で明示指定も可）。

**優先順位: CLI 引数 > config.toml > 既定値**

```toml
[defaults]
model        = "turbo"
language     = "ja"
format       = ["txt"]
device       = "cpu"
compute_type = "int8"

[pdf]
backend      = "pymupdf4llm"   # or "docling"

[logging]
level        = "info"
```

---

## 対応形式

**入力（transcribe）**: `.mp3 .wav .m4a .mp4 .mov .mkv`（動画は FFmpeg で音声抽出）
**出力（transcribe）**: `.txt`（時刻なし/つき）/ `.json`（word時刻・解析用）/ `.srt` `.vtt` `.ass`（字幕テロップ）/ `_preview.mp4`（`--preview`・焼き込み確認）
**入力（pdf）**: `.pdf` ／ **出力**: `.md`

---

## 終了コード

- `0` 全成功 / `1` 一部または全部失敗 / `2` 前提条件エラー（FFmpeg 未導入・入力なし・設定不正など）

---

## 仕組み・設計

```
src/transcripter/
├── cli.py                 # Typer サブコマンド（transcribe / pdf）
├── config.py              # TOML 読込 + 優先順位マージ
├── discovery.py           # 入力収集（拡張子集合を差し替えて再利用）
├── progress.py            # rich 進捗バー
├── logging_conf.py / errors.py
├── core/
│   ├── audio.py                    # FFmpeg 音声抽出
│   ├── digest.py                   # 動画ダイジェスト（静止画・コンタクトシート・digest.md）
│   ├── backend.py / faster_whisper_backend.py / transcriber.py
│   ├── whisperx_backend.py         # 任意: ±50ms整列＋話者分離（--extra whisperx）
│   ├── burnin.py                   # ffmpeg 字幕焼き込みプレビュー
│   ├── subtitle/
│   │   ├── model.py                # Cue（字幕1枚）
│   │   ├── reflow.py               # 整形エンジン（words → Cue・形態素/禁則/話者）
│   │   ├── morph.py                # 形態素解析アダプタ（fugashi/janome/sudachi）
│   │   ├── postprocess.py          # 辞書置換・フィラー除去・話者名整形
│   │   └── style.py                # SubtitleStyle＋プリセット（→ASS/ffmpeg）
│   └── pdf/
│       ├── backend.py              # PdfBackend 抽象
│       ├── pymupdf4llm_backend.py  # 既定（軽量）
│       ├── docling_backend.py      # 任意（高精度）
│       └── converter.py            # 変換オーケストレーション + バックエンド生成
├── output/
│   ├── writer.py / timefmt.py      # txt / json ＋ 字幕ディスパッチ
│   ├── srt.py / vtt.py / ass.py    # 字幕ライタ
│   └── markdown_writer.py          # md
└── webui/                          # 任意: ローカル Web UI（--extra webui）
    └── app.py                      # FastAPI ドラッグ&ドロップ
```

- **Backend 抽象**: 音声（faster-whisper ↔ 将来 whisper.cpp 等）も PDF（pymupdf4llm ↔ docling）も差し替え可能。
- **コア層を CLI から分離**: 将来 GUI / Web UI から同じ API を再利用できる。
- **失敗はファイル単位で握る**: 1 件失敗してもバッチは継続、処理済みは残る。

---

## 開発

```bash
uv sync --extra dev
uv run pytest            # 単体テスト（モデルDL・PDF実体不要、バックエンドはモック）
uv run ruff check src tests
```

---

## プライバシー

音声・動画・PDF・変換結果は**外部送信しません**。
通信は `transcribe` 初回の Whisper モデルダウンロード（HuggingFace Hub）と、
`--backend docling` 初回のモデルダウンロードのみ。事前取得すればオフライン実行できます。
PDF（pymupdf4llm）はモデル不要で完全ローカルです。

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| `FFmpeg が見つかりません` | 上記の手順で FFmpeg を導入（`pdf` のみなら不要） |
| `pytest`/`ruff` が無い | `uv sync --extra dev` |
| `docling がインストールされていません` | `uv sync --extra docling` |
| PDFの日本語が 1 文字ずつ空く | それは Docling+OCR の癖。デジタルPDFは既定の `pymupdf4llm` を使う |
| 文字起こしが遅い | CPUでは長尺は時間がかかる。2回目以降はモデルDL不要で短縮。`--vad` も有効 |
| プロジェクトを別パスへ移動した | [`MIGRATION.md`](MIGRATION.md) の手順（`.venv` 再生成・メモリ移行）を実行 |
