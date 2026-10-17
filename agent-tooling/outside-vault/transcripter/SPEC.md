# SPEC.md — ローカル音声/動画 文字起こし & PDF→Markdown ツール 仕様書

> ステータス: Phase 1（transcribe: txt/json、pdf: md）＋字幕テロップ Phase A/B/C **実装済み**
> （srt/vtt/ass・reflow整形・スタイル/焼き込みプレビュー・形態素解析・WhisperX/話者分離・ローカルGUI）
> 作成日: 2026-06-05 / 更新: 2026-07-24（字幕テロップ機能を実装・Phase C 完了）
> 対象: ローカルPC上で完結する個人用ツール
> 字幕テロップ（srt/vtt/ass ＋ DaVinci Resolve 連携）の設計・整形パラメータ・調査結果は
> **`docs/subtitle-telop-plan.md`** / **`docs/davinci-workflow.md`** を参照（本仕様書 §12・todo.md を統合）。
> 開発の経緯・機能追加/改善の履歴は **`CHANGELOG.md`** にまとめている。

### 確定済み方針（ユーザー回答反映）
- **実行環境**: NVIDIA GPU なし。**Apple Silicon Mac** → 既定は `device=cpu` / `compute_type=int8`。
- **用途**: 「字幕付与」と「単純トランスクリプト」の両方があり得る。**まずは時刻なしの単純トランスクリプト（txt）を実装**。字幕付与（srt/vtt + 時刻）は後続として `todo.md` に設計を分離。
- **既定言語**: `ja`。
- **PDF→Markdown** を同一CLIの `pdf` サブコマンドとして追加（§27）。

---

## 27. PDF → Markdown 変換（pdf サブコマンド）

### 27.1 背景・要件
- 個人用ツールに「PDF → Markdown」変換を統合したい。
- 対象例: 医療系の検査結果（**デジタルPDF・テキスト層あり・日本語・表中心**、機微な医療データ）。
- 方針: **ローカル完結**（クラウド/外部API変換に通さない）、最小依存、保守容易。

### 27.2 ツール調査（PDF→md）
| ツール | 方式 | 表精度 | 重さ | OCR | 備考 |
|--------|------|--------|------|-----|------|
| **PyMuPDF4LLM** | テキスト層直読 | 良 | 軽量・GPU不要 | 補助 | デジタルPDF最適 |
| Docling (IBM) | レイアウトML | 高 | 中（モデルDL） | 対応 | スキャン/複雑表向け |
| Marker | Surya OCR+ML | 高 | 重 | ◎ | 過剰 |
| MinerU | 多モデル | 高(CJK) | 重 | ◎(84言語) | スキャン時 |
| MarkItDown | 軽量抽出 | 低 | 軽 | 限定 | 構造弱い |

### 27.3 実測 A/B（表中心の日本語PDF・同一ファイル）
| 観点 | PyMuPDF4LLM | Docling |
|------|-------------|---------|
| 処理時間 | 数秒 | 79.4秒 |
| 表検出 | ◎ | ◎ |
| 日本語の質 | ◎ `\|大腸がん\|標準\|` | ⚠️ `\| 大 腸 がん \| 標 準 \|`（文字分割） |
| 依存 | 11パッケージ | 100パッケージ+OCRモデル |
| OCR | 不使用（テキスト層） | 自動OCR起動（CJK崩れ） |

→ **デジタルPDFでは PyMuPDF4LLM が速度・日本語・軽さで明確に優位**。Docling は OCR でテキスト層を作り直すため CJK が 1 文字ずつ分割。Docling は `do_ocr=False` で改善可能だが、デジタルPDFをわざわざ重い経路に通す利点が薄い。

### 27.4 採用
- **既定バックエンド = PyMuPDF4LLM**（軽量・ローカル・実証済み）。
- **任意バックエンド = Docling**（`--extra docling`。`do_ocr=False` 既定でテキスト層優先。スキャン時は OCR 有効化）。
- `PdfBackend` 抽象で差し替え可能（音声側 `Backend` と同思想）。

### 27.5 CLI / 構成
- `transcripter pdf <PDF...> [-o DIR] [-b pymupdf4llm|docling] [-r] [--overwrite]`
- 出力: `<入力名>.md`（出力先未指定なら入力と同じ場所）。
- 実装: `core/pdf/`（backend / pymupdf4llm_backend / docling_backend / converter）, `output/markdown_writer.py`。
- 設定: `config.toml` の `[pdf] backend = "..."`。

### 27.6 参照URL（PDF→md 調査）
- Marker vs MinerU vs MarkItDown: https://jimmysong.io/blog/pdf-to-markdown-open-source-deep-dive/
- Marker/Docling/MinerU/PyMuPDF4LLM 比較(2026): https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026
- PyMuPDF4LLM 公式ドキュメント: https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/
- Docling: https://github.com/docling-project/docling

---

---

## 1. ツール名案

| 案 | 由来 | コマンド名 |
|----|------|-----------|
| **transcripter**（第一候補） | リポジトリ名と一致、覚えやすい | `transcripter` / 短縮 `tsc` |
| voicetext | 用途が直感的 | `voicetext` |
| jascribe | 日本語(ja)中心を示唆 | `jascribe` |
| localwhisper | ローカル＋Whisper を明示 | `localwhisper` |

→ 本仕様では **`transcripter`**（CLI 名は `transcripter`、エイリアス `tsc`）を採用候補とする。

---

## 2. 目的

ローカル環境（クラウド・有料API非依存）で、音声・動画ファイルを高速・高精度に文字起こしする個人用ツールを作る。OpenAI Whisper の `turbo` モデルを中心に、日本語を主・英語/日英混在を従として扱う。

---

## 3. 想定ユーザー

- ツール作者本人（シニアエンジニア、CLI に習熟）
- 将来的に GUI を付ければ非エンジニアにも配布可能な構成を目指す
- プライバシー意識が高く、音声を外部送信したくないユーザー

---

## 4. 想定ユースケース

1. 音声メモ・音声入力のテキスト化
2. ラジオ/ポッドキャストなど長時間音声の文字起こし
3. 動画（mp4/mov/mkv）からの字幕（SRT/VTT）生成
4. 日本語音声の文字起こし（主用途）
5. 英語音声・日英混在音声の文字起こし（従用途）
6. 複数ファイルの一括バッチ処理

---

## 5. 対象OS

| OS | サポート | 備考 |
|----|---------|------|
| macOS (Apple Silicon / Intel) | ◎ | 作者環境（Darwin 25.5）。GPU は基本 CPU 動作。MPS は faster-whisper では未対応のため CPU/int8 で運用 |
| Windows 10/11 | ◎ | NVIDIA GPU があれば CUDA 利用可 |
| Linux | ◎ | NVIDIA GPU + CUDA が最も高速 |

OS 差分の詳細は §22・§付録参照。

---

## 6. 対象PCスペック（前提・未確定あり）

| 区分 | 想定 |
|------|------|
| 最低 | CPU 4 コア / RAM 8GB / ストレージ空き 5GB（turbo モデル約 1.5GB + FFmpeg + 依存） |
| 推奨 | CPU 8 コア以上 / RAM 16GB 以上 |
| GPU あり | NVIDIA GPU（VRAM 6GB 以上）+ CUDA 12 + cuDNN 9 |
| macOS | Apple Silicon の場合 CPU + int8 運用を基本とする |

> ⚠️ 作者の実機スペック（GPU 有無、RAM、Apple Silicon 世代）は **未確定** → §25 確認事項参照。

---

## 7. 使用技術候補

| カテゴリ | 候補 |
|----------|------|
| 言語 | Python 3.10–3.12 |
| 推論エンジン | **faster-whisper**（CTranslate2）/ openai-whisper / whisper.cpp / WhisperX |
| 音声・動画処理 | **FFmpeg**（外部バイナリ） |
| CLI | **Typer**（argparse より宣言的、補完容易）/ argparse |
| 進捗表示 | **rich**（プログレスバー＋ログ）/ tqdm |
| 字幕生成 | 自前実装 + `srt` ライブラリ（任意）/ faster-whisper の segment から生成 |
| 設定ファイル | **TOML**（`config.toml`、Python 3.11+ は標準 `tomllib`） |
| VAD | Silero VAD（faster-whisper 組込み `vad_filter=True`） |

---

## 8. 調査結果（要約）

### 8.1 Whisper `turbo` の位置づけ
- OpenAI が **2024年10月**にリリースした最新世代。正式名 `large-v3-turbo`、短縮名 `turbo`。
- `large-v3` を **プルーニング**し、デコーダ層を **32 → 4** に削減 → 約 **6倍高速**、品質劣化は 1–2% 程度（多くの言語で `large-v2` と同等）。
- **翻訳（translate）タスクは非対応**（学習データから翻訳を除外）。文字起こし（transcribe）専用。
- タイ語・広東語など一部言語で劣化が大きいが、**日本語は良好**。

### 8.2 openai-whisper での turbo
- `whisper.load_model("turbo")` でロード。CLI では `whisper audio.wav`（v20240930 以降 turbo がデフォルト）。
- 出力は `--output_format txt|vtt|srt|tsv|json|all`。Python では `whisper.utils.get_writer` で各形式を書き出せる。
- PyTorch ベースで CPU は遅め。GPU(CUDA) 推奨。Apple Silicon は MPS 一部対応だが不安定。

### 8.3 faster-whisper での turbo
- `WhisperModel("turbo", device=..., compute_type=...)` でロード。**モデル名文字列は `"turbo"`**。
- CTranslate2 実装で **openai-whisper の約4倍高速・低メモリ**。int8 量子化で CPU/GPU ともさらに高速化。
- **VAD（Silero）が組込み**。デフォルトは無効、`vad_filter=True` で有効化。`vad_parameters` で `min_silence_duration_ms` 等を調整可。
- `word_timestamps=True` で単語単位タイムスタンプ取得可（`segment.words`）。
- 字幕は segment（start/end/text）から自前で SRT/VTT を生成。

### 8.4 CPU/GPU 別推奨設定
| 環境 | device | compute_type | 備考 |
|------|--------|--------------|------|
| NVIDIA GPU | `cuda` | `float16`（標準）/ `int8_float16`（省メモリ） | CUDA 12 + cuDNN 9 必須 |
| CPU（一般） | `cpu` | `int8`（推奨）/ `float32`（高精度） | スレッド数 `cpu_threads` を CPU コア数に合わせる |
| macOS Apple Silicon | `cpu` | `int8` | faster-whisper は MPS 非対応。CPU int8 で運用 |
| 自動 | `auto` | `default` | device 自動判定（ライブラリ既定） |

### 8.5 FFmpeg による入力対応
- 動画/音声を 16kHz モノラル PCM(wav) に変換して Whisper に渡すのが定石。
- 例: `ffmpeg -i input.mp4 -ar 16000 -ac 1 -c:a pcm_s16le output.wav`
- faster-whisper / openai-whisper は内部で FFmpeg を呼ぶため、ファイルパス直接渡しも可能だが、**動画→音声抽出を明示的に行う**ことで対応形式とエラー原因を制御しやすくする。

### 8.6 SRT / VTT / TXT / JSON 出力
- **TXT**: segment テキストを連結。
- **SRT**: `index` + `HH:MM:SS,mmm --> HH:MM:SS,mmm` + テキスト。
- **VTT**: 先頭 `WEBVTT` + `HH:MM:SS.mmm --> HH:MM:SS.mmm`。
- **JSON**: segment 配列（start/end/text、任意で words/language/duration）を保存。再処理・解析用。
- openai-whisper は `get_writer` で標準提供。faster-whisper は自前生成（実装容易、本ツールでは統一フォーマッタを自作）。

### 8.7 長時間音声のベストプラクティス
- segment は逐次生成（faster-whisper は generator）→ メモリに全保持せずストリーム処理。
- 進捗は `info.duration` と segment の `end` から算出して表示。
- 失敗に備え、処理済み出力は逐次フラッシュ／ファイル単位でコミット。
- クリーンな音声（ノイズ除去）が精度に最も効く。

### 8.8 VAD・無音除去・チャンク分割
- faster-whisper の **Silero VAD は軽量**（30秒チャンクを CPU 1スレッドで 1ms 未満）。
- 長い無音やノイズ区間でのハルシネーション（幻聴的な誤出力）を抑制 → ラジオ等で有効。
- デフォルト値で概ね良好。音声タイプに応じて `min_silence_duration_ms` を調整。
- turbo + VAD は長時間ファイルでの安定処理に推奨。

### 8.9 WhisperX を使う/使わないケース
- **使う**: ±50ms 精度の単語タイムスタンプ（wav2vec2 forced alignment）、話者分離（pyannote）が必要なとき。内部で faster-whisper を呼ぶ。
- **使わない**: 単純な文字起こし/字幕で十分なとき。複数モデルを読むため重く、依存（pyannote, HuggingFace トークン）が増える。
- → **実装済み（任意 extra）**: `--backend whisperx`（`--extra whisperx`）で連携。既定は faster-whisper のまま。

### 8.10 配布・実行しやすい構成
- Python パッケージ（`pyproject.toml`）+ `pipx` / `uv` でインストール。CLI エントリポイント提供。
- FFmpeg は外部依存（OS パッケージマネージャで導入）。起動時に存在チェック。
- モデルは初回実行時に HuggingFace から自動 DL（キャッシュ先を明示）。
- 将来 GUI 化のためコア処理をライブラリ層（`core/`）に分離。

---

## 9. ライブラリ比較

| 観点 | openai-whisper | **faster-whisper** | whisper.cpp | WhisperX |
|------|----------------|--------------------|-------------|----------|
| 精度（turbo） | ◎ 基準 | ◎ 同等 | ○（量子化で微減） | ◎（+整列で時刻精度↑） |
| 速度 | △ 遅い | ◎ 約4倍速 | ○〜◎（CPU/Metal最適） | ○（追加処理で重い） |
| GPU 対応 | ◎ CUDA / △MPS | ◎ CUDA(12) | ◎ CUDA/Metal/Vulkan | ◎ CUDA |
| CPU 対応 | △ 遅い | ◎ int8 で良好 | ◎ 最適化済 | ○ |
| メモリ使用量 | 多 | 少（量子化） | 少 | 多（複数モデル） |
| インストール容易さ | ◎ pip | ◎ pip（GPUはcuDNN必要） | △ ビルド/バイナリ | △ 依存多い |
| 字幕出力 | ◎ 標準writer | ○ 自前生成 | ○ 標準で srt/vtt | ◎ 単語単位 |
| 長時間音声 | ○ | ◎ VAD+stream | ○ | ◎ |
| 日本語 | ◎ | ◎ | ○〜◎ | ◎ |
| Windows | ◎ | ◎ | ◎ | ○ |
| macOS | ◎(CPU/MPS) | ◎(CPU) | ◎(Metal) | ○ |
| Linux | ◎ | ◎ | ◎ | ◎ |
| 将来GUI化 | ○ | ◎（純Python・軽量） | △（別プロセス連携） | ○ |

**結論**: コア推論は **faster-whisper** が速度・メモリ・GUI 化容易さで最適。Apple Silicon で Metal を最大活用したい場合は whisper.cpp が候補になるため、**バックエンド差し替え可能な設計**にする（§10）。

---

## 10. 最終的に採用する技術スタック案

| レイヤ | 採用 | 理由 |
|--------|------|------|
| 言語 | **Python 3.10+** | 依存・GUI 化・エコシステム |
| 推論 | **faster-whisper（turbo）** | 速度4倍・低メモリ・VAD組込・純Python |
| バックエンド抽象化 | `Backend` インターフェース | 将来 whisper.cpp / openai-whisper 差し替え可 |
| 音声/動画 | **FFmpeg**（外部バイナリ） | 入力形式網羅・音声抽出 |
| CLI | **Typer** | サブコマンド・補完・型ヒント |
| 進捗/ログ | **rich** | プログレスバー＋整形ログを一元化 |
| 字幕生成 | 自前フォーマッタ（txt/srt/vtt/json） | 依存最小・出力統一 |
| 設定 | **config.toml**（`tomllib`/`tomli`） | 標準ライブラリで読める |
| パッケージング | `pyproject.toml` + uv/pipx | 配布容易 |

> 第一候補（faster-whisper + FFmpeg + Typer + rich + TOML）を採用。tqdm より rich、YAML より TOML（標準ライブラリ対応）を選択。

---

## 11. MVP 機能

- 単一/複数ファイルの文字起こし（turbo、デフォルト言語 `ja`）
- 入力: `.mp3 .wav .m4a .mp4 .mov .mkv`（動画は FFmpeg で音声抽出）
- 出力: `.txt .srt .vtt .json`（複数同時出力可）
- device/compute_type 指定（auto / cpu / cuda、int8 / float16 等）
- VAD on/off
- タイムスタンプ出力有無
- 出力先ディレクトリ指定（既定: 入力と同じ場所）
- ディレクトリ指定での一括処理
- 進捗表示・ログ・失敗時の途中成果物保持

---

## 12. 非MVP機能（将来）

- WhisperX 連携（forced alignment / 単語単位 ±50ms）
- 話者分離（pyannote）
- ローカル Web UI / ドラッグ&ドロップ GUI
- 字幕自動整形（行長・改行・最大文字数）
- LLM による句読点・表記ゆれ補正（ローカル LLM 優先、外部 API は任意）
- バックエンド切替（whisper.cpp / openai-whisper）
- リアルタイム/マイク入力
- 文字起こし結果のキャッシュ・差分再実行

---

## 13. CLI 仕様

```bash
# 基本
transcripter INPUT [OPTIONS]

# 単一ファイル
transcripter input.mp3 --model turbo --language ja --format srt --output ./outputs

# ディレクトリ一括 + VAD + 複数形式
transcripter ./audios --language ja --format txt,srt --vad --output ./out

# GPU 明示
transcripter input.mp4 --device cuda --compute-type float16 --format vtt
```

### オプション一覧

| オプション | 既定 | 説明 |
|-----------|------|------|
| `INPUT`（位置引数） | — | ファイル or ディレクトリ（複数可） |
| `--model` | `turbo` | Whisper モデル名 |
| `--language` / `-l` | `ja` | 言語コード（`auto` で自動判定） |
| `--format` / `-f` | `txt` | `txt,srt,vtt,json`（カンマ区切りで複数） |
| `--output` / `-o` | 入力と同じ | 出力ディレクトリ |
| `--device` | `cpu`（実装既定。SPECの当初案は `auto`） | `auto,cpu,cuda` |
| `--compute-type` | `int8`（実装既定） | `int8,float16,int8_float16,float32` |
| `--vad / --no-vad` | `--no-vad` | VAD 有効/無効 |
| `--timestamps / --no-timestamps` | `--no-timestamps`（実装既定。字幕系は plan 参照） | txt に時刻を付けるか |
| `--word-timestamps` | off | 単語単位（json/将来字幕用） |
| `--recursive / -r` | off | ディレクトリ再帰探索 |
| `--config` | `./config.toml` | 設定ファイルパス |
| `--cpu-threads` | 自動 | CPU スレッド数 |
| `--beam-size` | 5 | デコードビーム幅 |
| `--overwrite` | off | 既存出力を上書き |
| `--log-level` | `info` | `debug,info,warning,error` |
| `--log-file` | なし | ログ出力ファイル |
| `--version` / `--help` | — | 標準 |

設定の優先順位: **CLI 引数 > config.toml > 既定値**。

---

## 14. 設定ファイル仕様（config.toml）

```toml
[defaults]
model         = "turbo"
language      = "ja"
format        = ["txt", "srt"]
output_dir    = ""          # 空なら入力と同じ場所
device        = "auto"      # auto | cpu | cuda
compute_type  = ""          # 空なら device から自動決定
vad           = false
timestamps    = true
word_timestamps = false
beam_size     = 5
cpu_threads   = 0           # 0 = 自動

[vad]
min_silence_duration_ms = 500
# 他 Silero VAD パラメータを任意で追加

[paths]
model_cache   = ""          # 空なら既定キャッシュ（§16.4）
ffmpeg        = "ffmpeg"     # PATH 上の名前 or 絶対パス

[logging]
level         = "info"
file          = ""          # 空ならコンソールのみ
```

---

## 15. 入力ファイル仕様

| 種別 | 拡張子 | 処理 |
|------|--------|------|
| 音声 | `.mp3 .wav .m4a` | （必要に応じ）FFmpeg で 16kHz/mono/wav に正規化 |
| 動画 | `.mp4 .mov .mkv` | FFmpeg で音声トラック抽出 → 16kHz/mono/wav |

- 入力がディレクトリの場合、対応拡張子を探索（`--recursive` で再帰）。
- 非対応形式はスキップし警告ログ。
- 抽出した一時 wav は処理後に削除（`--keep-temp` で保持可・将来）。
- 破損ファイル/音声トラックなしは個別エラーとして記録し、次のファイルへ継続。

---

## 16. 出力ファイル仕様

### 16.1 命名規則
- `<入力ファイル名（拡張子除く）>.<format>`（例: `radio_001.srt`）
- 出力先: `--output` 指定があればそこ、なければ入力と同じディレクトリ。
- 同名既存ファイルは `--overwrite` がなければスキップ（警告）。

### 16.2 各形式
- **TXT**: 全 segment テキストを連結（`--timestamps` 時は `[HH:MM:SS] text` 形式も可）。
- **SRT**:
  ```
  1
  00:00:00,000 --> 00:00:03,200
  こんにちは
  ```
- **VTT**:
  ```
  WEBVTT

  00:00:00.000 --> 00:00:03.200
  こんにちは
  ```
- **JSON**: メタ情報付き。
  ```json
  {
    "file": "input.mp3",
    "language": "ja",
    "duration": 123.4,
    "model": "turbo",
    "segments": [
      {"id":0,"start":0.0,"end":3.2,"text":"こんにちは","words":[]}
    ]
  }
  ```

### 16.3 部分成果物
- segment 逐次処理。長時間ファイルは一定間隔で中間 JSON をフラッシュ（クラッシュ耐性）。

### 16.4 モデルキャッシュ場所（明示）
| OS | 既定キャッシュ |
|----|---------------|
| すべて（HuggingFace Hub） | `~/.cache/huggingface/hub`（環境変数 `HF_HOME` で変更可） |
| 本ツール設定 | `[paths].model_cache` で上書き、内部で `HF_HOME` を設定 |

初回実行時に turbo モデル（約 1.5GB）を DL。ダウンロード進捗をログ表示。

---

## 17. ディレクトリ構成案

```
transcripter/
├── pyproject.toml
├── README.md
├── SPEC.md
├── config.example.toml
├── src/
│   └── transcripter/
│       ├── __init__.py
│       ├── cli.py            # Typer エントリポイント
│       ├── config.py         # TOML 読込・既定値マージ
│       ├── core/
│       │   ├── backend.py    # Backend 抽象インターフェース
│       │   ├── faster_whisper_backend.py
│       │   ├── audio.py      # FFmpeg 抽出・正規化
│       │   ├── transcriber.py# 文字起こしオーケストレーション
│       │   └── vad.py        # VAD 設定
│       ├── output/
│       │   ├── writer.py     # 統一ライタ
│       │   ├── srt.py
│       │   ├── vtt.py
│       │   ├── txt.py
│       │   └── json_out.py
│       ├── progress.py       # rich プログレス
│       ├── logging_conf.py
│       └── errors.py
├── tests/
│   ├── test_audio.py
│   ├── test_writers.py
│   ├── test_config.py
│   └── fixtures/             # 短いサンプル音声
└── (将来) webui/             # Phase 3
```

> コア処理を `core/` + `output/` に分離し、CLI とは疎結合 → GUI/Web UI から同じ API を再利用。

---

## 18. 処理フロー

```
1. CLI 解析（Typer）→ config.toml マージ → 実効設定確定
2. 事前チェック: FFmpeg 存在 / 入力存在 / 出力先書込可 / device 利用可否
3. 入力収集: ファイル/ディレクトリ展開 → 対応拡張子フィルタ
4. モデルロード: WhisperModel("turbo", device, compute_type)（初回 DL）
5. ファイルごとにループ:
   a. 動画なら FFmpeg で音声抽出 → 16kHz/mono wav（一時ファイル）
   b. transcribe(audio, language, vad_filter, word_timestamps, beam_size)
   c. segment を逐次受信 → 進捗更新（end/duration）→ 中間バッファ
   d. 指定 format ごとに出力ファイル書込
   e. 一時ファイル削除
   f. 成功/失敗をサマリに記録（失敗しても次へ継続）
6. 全体サマリ表示（成功 N / 失敗 M / 出力先）
7. 失敗があれば非ゼロ終了コード
```

---

## 19. エラーハンドリング方針

| 事象 | 対応 |
|------|------|
| FFmpeg 未インストール | 起動時に検出、導入手順を提示して終了（exit 2） |
| 入力ファイルなし/非対応 | 警告ログ、当該ファイルをスキップ |
| 音声トラックなし/破損 | 個別エラー記録、次ファイルへ継続 |
| CUDA/cuDNN 不整合 | 明確なメッセージ＋`--device cpu` へのフォールバック案内（自動フォールバックは設定で可） |
| モデル DL 失敗（ネット断） | リトライ案内、キャッシュ場所明示 |
| 出力先書込不可 | 事前チェックで停止、権限エラー明示 |
| 途中クラッシュ | 中間 JSON / 完了済みファイルは保持 |

- 全エラーに**原因＋対処**を含むメッセージ。スタックトレースは `--log-level debug` 時のみ詳細表示。
- 終了コード: 0=全成功, 1=一部失敗, 2=前提条件エラー。

---

## 20. ログ方針

- **rich** ベース。コンソールは人間向け整形、`--log-file` 指定時は同内容をプレーンに保存。
- レベル: `debug / info / warning / error`。
- info: ファイル開始/完了、検出言語、所要時間、出力パス。
- debug: FFmpeg コマンド、モデル設定、segment 詳細、スタックトレース。
- 進捗バーは長時間ファイルで残り時間の目安を表示（duration ベース）。
- 機微情報（音声内容）はログに不要な限り出さない。

---

## 21. テスト方針

| レベル | 内容 |
|--------|------|
| 単体 | writer（srt/vtt/txt/json の時刻整形・エスケープ）、config マージ、拡張子フィルタ、時刻フォーマッタ |
| 結合 | 短いサンプル音声（数秒、日本語/英語）で transcribe→出力までを検証（モデルは小型 or モック） |
| FFmpeg | 動画→音声抽出の存在/コマンド検証（FFmpeg をモック or 実バイナリ） |
| 異常系 | 非対応拡張子・破損ファイル・出力先権限・device 不正 |
| CI（任意） | lint（ruff）+ 型（mypy）+ pytest。重いモデル DL は CI ではスキップ/キャッシュ |

- 決定論性のため beam_size 固定・短尺 fixture を使用。
- モデル推論はコスト高のため、コアロジックはバックエンドをモックして検証。

---

## 22. パフォーマンス上の注意

- **GPU(CUDA)**: `float16` 標準、VRAM 不足時 `int8_float16`。CUDA 12 / cuDNN 9 必須。
- **CPU**: `int8` + `cpu_threads` をコア数に合わせる。turbo でも長時間は時間がかかる旨を周知。
- **macOS Apple Silicon**: faster-whisper は MPS 非対応 → CPU `int8` 運用。Metal を最大活用したい場合は whisper.cpp バックエンド（Phase 3）を検討。
- segment はストリーム処理しメモリ常駐を避ける。
- VAD 有効化で無音/ノイズ区間のハルシネーションと処理時間を削減（ラジオ等に有効）。
- バッチ処理ではモデルを 1 回だけロードし全ファイルで再利用。

---

## 23. セキュリティ・プライバシー方針

- 音声・動画・文字起こし結果を**外部サーバへ送信しない**（完全ローカル処理）。
- 唯一のネットワークアクセスは**初回のモデルダウンロード**（HuggingFace Hub）。オフライン運用は事前 DL 済みキャッシュで可能。
- 一時ファイル（抽出 wav）は処理後削除。保存先はユーザーが制御。
- LLM 補正（Phase 3）は**ローカル LLM を既定**、外部 API はオプトインの任意機能とし、その旨を明示。
- ログに音声内容を不必要に残さない。

---

## 24. 実装ステップ（フェーズ別）

### Phase 1: CLI MVP（時刻なしトランスクリプト優先）
> **最初の実装目標**: 時刻を付与しない単純トランスクリプト（`.txt`）。既定 `device=cpu` / `compute_type=int8` / `language=ja`。字幕（srt/vtt + 時刻）は `todo.md` 参照で後続実装。
1. プロジェクト雛形（`pyproject.toml`、`src/transcripter`、依存: faster-whisper, typer, rich）
2. FFmpeg 存在チェック + 動画→音声抽出（`core/audio.py`）
3. `Backend` 抽象 + faster-whisper 実装（turbo ロード、cpu/int8 既定、transcribe）
4. 出力ライタ: **txt（時刻なし、全segment連結）を最初に**。json（解析用）を併設。srt/vtt は Phase 1.5（todo.md）。
5. CLI（単一ファイル、`--model/--language/--format/--output`、device/compute_type）
6. 日本語デフォルト・基本ログ
7. 単体テスト（txt/json writer・config・拡張子フィルタ）

### Phase 2: 実用機能
1. 複数ファイル/ディレクトリ一括（`--recursive`）
2. VAD（`--vad` + vad_parameters）
3. rich プログレスバー（duration ベース）
4. config.toml 対応（優先順位マージ）
5. ログファイル出力・レベル制御
6. エラー時の継続処理・中間成果物保持・リトライ
7. 終了コード設計・サマリ表示

### Phase 3: 高度機能
1. ✅ WhisperX 連携（forced alignment / 単語単位）— `--backend whisperx`（`--extra whisperx`）
2. ✅ 話者分離（pyannote、HF トークン設定）— `--diarize` / `--speaker-labels`
3. ✅ ローカル Web UI（FastAPI）+ ドラッグ&ドロップ — `transcripter serve`（`--extra webui`）
4. ✅ 字幕自動整形（行長/改行/最大文字数）— reflow エンジン（形態素解析＋禁則）
5. ✅ LLM 句読点・表記ゆれ補正（ローカル優先、外部 API は任意）— `--llm-correct`（既定 ollama＝ローカル / anthropic はオプトイン）。前処理 `--denoise`・語彙ヒント `--vocab`・`--accurate` も追加
6. バックエンド切替（whisper.cpp / openai-whisper）— 未実装（Backend 抽象で拡張可能）

---

## 25. 確認事項（回答状況）

### 回答済み（確定）
1. ✅ **GPU環境**: NVIDIA GPU **なし** → CPU 運用。
2. ✅ **OS/チップ**: **Apple Silicon Mac** → 既定 `device=cpu` / `compute_type=int8`（faster-whisper は MPS 非対応のため CPU 運用で合意）。
3. ✅ **主用途**: 字幕付与・単純トランスクリプトの**両方**。**まず時刻なし txt を実装**、字幕は `todo.md` に設計分離。
4. ✅ **既定言語**: `ja` 固定。

### 未確定（実装中に既定で進め、必要時に確認）
5. **出力既定形式**: 当面 `txt` を既定（字幕実装後に `txt+srt` 同時の要否を再検討）。
6. **パッケージ管理**: 既定は `uv`（高速・Apple Silicon相性良）を想定。`venv+pip` も手順提供。
7. **設定ファイル形式**: TOML で進める（標準 `tomllib`）。異論あれば変更。
8. **ツール名**: `transcripter`（CLI `transcripter` / `tsc`）で進める。
9. **一時ファイル保持**: 抽出 wav は既定で削除（`--keep-temp` で保持）。
10. **モデルキャッシュ**: 既定 `~/.cache/huggingface`（`[paths].model_cache` で変更可）。

---

## 26. 参照URL一覧

- OpenAI Whisper 公式リポジトリ: https://github.com/openai/whisper
- Whisper `turbo` リリース議論（Discussion #2363）: https://github.com/openai/whisper/discussions/2363
- whisper-large-v3-turbo モデルカード（Hugging Face）: https://huggingface.co/openai/whisper-large-v3-turbo
- openai-whisper `transcribe.py`（出力 writer）: https://github.com/openai/whisper/blob/main/whisper/transcribe.py
- Whisper で SRT/VTT を書く方法（Discussion #911）: https://github.com/openai/whisper/discussions/911
- faster-whisper（SYSTRAN）リポジトリ: https://github.com/SYSTRAN/faster-whisper
- faster-whisper README（turbo/VAD/compute_type/CUDA要件/word_timestamps）: https://github.com/SYSTRAN/faster-whisper/blob/master/README.md
- faster-whisper turbo ベンチ（Issue #1030）: https://github.com/SYSTRAN/faster-whisper/issues/1030
- whisper.cpp（ggml-org）リポジトリ: https://github.com/ggml-org/whisper.cpp
- whisper.cpp モデル README: https://github.com/ggml-org/whisper.cpp/blob/master/models/README.md
- WhisperX（m-bain）リポジトリ: https://github.com/m-bain/whisperX
- Whisper 派生比較（Modal blog）: https://modal.com/blog/choosing-whisper-variants
- Whisper turbo 解説（Amgad Hasan）: https://amgadhasan.substack.com/p/demystifying-openais-new-whisper

---

> 次のアクション: 上記 §25 の確認事項にご回答いただいた後、合意が取れ次第「実装開始」のご指示で Phase 1 に着手します。
