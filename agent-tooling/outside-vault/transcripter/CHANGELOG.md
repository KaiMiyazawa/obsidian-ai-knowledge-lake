# CHANGELOG / 開発履歴

transcripter の機能追加・改善の履歴と、その背景（なぜそうしたか）をまとめる。
細かな仕様は `SPEC.md`、字幕機能の設計は [`docs/subtitle-telop-plan.md`](docs/subtitle-telop-plan.md)、
使い方は `README.md` を参照。日付は開発日（個人開発のため簡易運用）。

---

## 背景・設計方針（なぜこの形か）

- **ローカル完結が大前提**: 音声・動画・PDF・変換結果を外部へ送信しない。通信はモデルの
  初回DLのみ。唯一の例外が「外部API後補正（オプトイン）」で、これは既定OFF＋明示許可時のみ。
- **DaVinci Resolve 連携は SRT が本命**: 調査の結果、Resolve は SRT を確実に取り込む一方
  ASS/SSA の装飾はほぼ無視する。→ 成果物は「整形済み SRT」、見た目は Resolve のインスペクタ＋
  トラックプリセットで作る。ASS/焼き込みプレビューは「確認・可視化」用と位置づけた。
- **中核は reflow エンジン**: Whisper の word 時刻から、無音ギャップ/句読点/文字数/表示秒で
  字幕を再分割し、読みやすい行長・表示時間・改行に整える。ここがツールの価値。
- **重い依存は任意 extra＋段階的縮退**: WhisperX/pyannote・形態素解析・GUI・LLM補正は
  すべてオプション。未導入でも既定機能は軽量に動く。
- **精度は「層で積む」**: 単一の万能策はなく、前処理→語彙ヒント→モデル→LLM後補正の順で
  費用対効果を見ながら重ねる設計にした（下記 精度向上を参照）。

---

## 履歴

### 2026-09-22 — `digest` 追加・保管場所の整理

- **`transcripter digest`** を追加（`core/digest.py`）。動画から時刻付き発話＋一定間隔の静止画＋コンタクトシートを
  作り、AI が読む `digest.md` にまとめる。背景: Claude Code は動画を直接読めないため、
  「文字起こし（Whisper）＋静止画（ffmpeg）」の組み合わせで内容を把握させる。外部送信なし。
  静止画は `-ss` の位置指定で抽出（4K/120fps で `fps` フィルタが全フレーム復号して遅いため）。
- **置き場所を変更**: `~/Desktop/transcripter` → `~/Documents/transcripter`（コードのみ Git 管理・GitHub private）。
  データは分離: 文字起こしテキスト・メモは保管庫 `09_investment/`、音声・サンプル動画は
  `~/Documents/transcripter-media/`、素材動画は `~/Movies/`、機微なPDFは保管庫 `health/documents/`。
- `uv.lock` を Git 管理に変更（再現性のため）。
- **PDF→Markdown の文字正規化**: 抽出テキストに混ざる部首の別字（⽇⽉⻑ など）と中黒の別字を NFKC＋個別置換で通常の字に直す
  （見た目は同じでも grep にヒットしないため）。`output/markdown_writer.py` の `normalize_pdf_text`。

### 2026-07-25 — 既定スタイルの調整・認識精度の強化・ドキュメント整備

**ドキュメント整理**
- 実装済みなのに「計画中」「MVP不採用」等と食い違っていた記述を一掃
  （README ステータス、SPEC §8.9・ロードマップ Phase 3、plan のフェーズ表記、
  未確定事項→決定事項）。

**字幕の既定スタイル調整（ユーザー指定）**
- 縁取りを既定 OFF に（白文字のみ）。※明るい背景では `--sub-preset box` 等を推奨。
- フォントサイズを段階的に縮小：フレーム高の 9% → 4.5% → **4.0%**。
- **一枚一行化**：`max_lines` 2 → 1。
- **一続きの文を1枚にまとめる**：`max_chars_per_cue` 28 → 20 →（要望で）**32**。
  句点(。！？)では必ず区切りつつ、句点のない一続きの発話は1枚に載る。
- **イタリック対応**：`SubtitleStyle.font_italic` ＋ `--sub-italic` を追加
  （和文に本来の斜体字形は無く、レンダラの疑似オブリークで傾ける）。
- フォント調査で **既定の `Noto Sans JP` は本Macに未導入**と判明 → 焼き込み時は
  `--sub-font "Hiragino Sans W6"` 等インストール済みフォントの指定を推奨と明記。
  Hiragino / YuGothic / イタリックの比較プレビューを作成。
- README に「字幕テロップのスタイル」節を新設（既定一覧＋italic/size/position/font の変更方法）。

**認識精度の強化（A〜D を実装）**
- **A. 前処理＋語彙ヒント**（ローカル・低コスト）
  - `--denoise`：風切り音・ノイズ低減＋音量正規化（`highpass+afftdn+loudnorm`）。
  - `--vocab` / `--initial-prompt`：固有名詞を Whisper の initial_prompt に渡し認識をバイアス。
  - `--no-condition-previous`：直前テキスト条件付けを切りループ幻覚を抑制。
  - 実機で明確な改善を確認（例：`14月3日→30、40ってさ`、`3 21→3、2、1`、`だ僕は→まだ僕は`）。
    処理は turbo 実機で約36秒。
- **B. 精度優先プリセット** `--accurate`（large-v3・VAD・条件付けOFF・denoise）。CPUでは低速。
- **C. ローカルLLM後補正** `--llm-correct`（既定 backend=ollama・外部送信なし）。
  Ollama＋日本語モデル（例 `qwen2.5:7b`）で誤変換・句読点を後補正。
- **D. 外部API後補正** `--llm-backend anthropic`（★オプトイン・課金・音声由来テキストが
  外部へ・既定OFF・送信警告つき）。
- LLM後補正は共通して「本文のみ・1対1・言い換え禁止・失敗時は原文維持」で、
  タイミング（word時刻・字幕区間）は変更しない。実装は `core/correct/`（urllib、新規依存なし）。
- テスト 64 → **80 件**。

### 2026-07-24 — 字幕テロップ機能 Phase A / B / C

- **Phase A（字幕の中核）**: reflow エンジン（`core/subtitle/` = model/reflow/postprocess/style/
  morph）、`srt`/`vtt` 出力、用語辞書 `--term-dict`、フィラー除去 `--strip-fillers`。
- **Phase B（スタイルと確認）**: `ass` 出力＋スタイル（プリセット outline/box/cinema）、
  ffmpeg 焼き込みプレビュー `--preview`（既定1080p30ダウンスケール）、DaVinci 手順
  [`docs/davinci-workflow.md`](docs/davinci-workflow.md)。
- **形態素解析による語境界改行**（fugashi→janome→sudachi 自動検出・未導入時は禁則ヒューリスティック、
  `--extra morph` / `--sub-morph`）。ユーザー提案を受けて禁則単独から切替。
- **Phase C（高度化）**: WhisperX バックエンド（`--backend whisperx`・±50ms整列、`--extra whisperx`）、
  話者分離＋ラベル（pyannote・`--diarize`/`--speaker-labels`）、ローカル GUI
  （`transcripter serve`・FastAPI・`--extra webui`）。
- 設計・調査は [`docs/subtitle-telop-plan.md`](docs/subtitle-telop-plan.md) に集約（`todo.md` を統合）。
- アクションカメラの旅（歩きしゃべり）動画で焼き込み E2E を確認。

### （初期）Phase 1–2 — CLI MVP と実用機能

- **Phase 1（CLI MVP）**: 音声/動画 → `txt`/`json`（faster-whisper turbo・Apple Silicon は
  `device=cpu`/`compute_type=int8`）、PDF → `md`（PyMuPDF4LLM）。Backend 抽象でエンジン差し替え可能。
- **Phase 2（実用機能）**: 複数ファイル/ディレクトリ一括 `--recursive`、VAD `--vad`、
  rich 進捗バー、`config.toml`（優先順位マージ）、ログ、ファイル単位の継続処理・終了コード。
- PDF は高精度バックエンド Docling を任意 extra（`--extra docling`）で追加。検証の結果、
  テキスト層のあるデジタル日本語PDFは pymupdf4llm が速度・精度で最良と確認。

---

## 未実装 / 今後の候補

- 2パスの **語彙自動抽出**（1回目の認識結果から固有名詞を拾い `--vocab` に自動投入）。
- LLM後補正の **cue分割の境界最適化**（32字超で切る際に読点「、」・句境界を優先）。
- バックエンド切替（whisper.cpp / openai-whisper）。
- Resolve Studio 向けの SRT 自動取り込み（`scripts/davinci_import_srt.py` は best-effort の下地）。
