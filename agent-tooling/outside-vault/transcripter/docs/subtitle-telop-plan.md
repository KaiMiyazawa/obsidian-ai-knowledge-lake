# 字幕テロップ補助機能 — 全体計画（design & plan）

> ステータス: **Phase A / B / C すべて実装済み**（srt/vtt/ass ＋ reflow整形 ＋ スタイル/焼き込みプレビュー ＋ 形態素解析 ＋ WhisperX/話者分離 ＋ ローカルGUI） / 作成: 2026-07-14 / 更新: 2026-07-24
> 位置づけ: `todo.md`（字幕出力の初期メモ）を置き換える正式な設計・実装計画。
> 上位仕様は `SPEC.md`、使い方は `README.md`、DaVinci 手順は `docs/davinci-workflow.md` を参照。

---

## 0. ゴールと理想状態

**やりたいこと**: 動画（一人喋り／旅の道中で音声が入っている等）から、**自動で字幕テロップを生成**し、
最終的に編集者が **DaVinci Resolve で微修正するだけ**で仕上がる状態にする。

**理想状態（Definition of Done のイメージ）**:
1. 動画を入れると、**読みやすく区切られた字幕**（1行の文字数・行数・表示時間・改行位置が整った状態）が出る。
2. 話者名や専門用語の誤変換が**自動修正**されている（例: 引地。既存の[表記修正ルール](../.claude/... のメモリ)を流用）。
3. フィラー（えー・あの・まあ）が任意で除去され、テロップとして自然。
4. DaVinci Resolve に取り込むと、**保存済みのトラックプリセットを一度当てるだけ**で、指定したフォント・帯（背景）・不透明度・縁取り・位置になる。
5. 取り込み前に**焼き込みプレビュー（burn-in mp4）**で見た目とタイミングを確認できる。

---

## 1. 調査結果と、そこから導く設計上の結論（最重要）

字幕自動化ツールは Claude Code × Whisper の作例が多数あり（末尾 §12 参照）、DaVinci 連携には**明確な制約**がある。これを踏まえないと「編集者が微修正だけ」が成立しない。

### 1.1 DaVinci Resolve の字幕取り込みの実態
- **SRT は確実に取り込める。** メディアプールへドラッグ or `File > Import Subtitle` で字幕トラック（ST1）が生成される。
- **ASS/SSA は「読み込めるが装飾はほぼ無視」。** 装飾を保持したい場合、実務では ASS→SRT に変換してから取り込むのが定石。
- **見た目（フォント/帯/不透明度/縁取り/位置/影）は DaVinci 側のインスペクタでトラックに一括適用**する。SRT/VTT はテキスト＋時刻しか持てず、**装飾は入らない**。
- **その見た目はトラックプリセットとして保存・再利用できる**（字幕クリップ選択 → Video タブの「…」メニュー →「トラックをプリセットとして保存」。フォント・サイズ・位置・スケール・ドロップシャドウ等を保持し、別タイムライン/プロジェクトでも再利用可）。
- **プログラムからの Text+ 自動生成は不安定**。無料版は外部 Python API 非対応（コンソール/メニュー実行のみ）、Fusion の Text+ 自動配置は UI 操作依存で壊れやすい、という報告が複数。→ **自動テロップ挿入の本命は「整形済み SRT」＋「保存済みトラックプリセット」**であり、Text+ の自動生成に依存しない。

### 1.2 結論（本ツールの役割分担）
| 領域 | 本ツールがやること | DaVinci 側でやること |
|------|------------------|--------------------|
| **文字（テキスト＋区切り）** | 高品質な整形済み SRT/VTT を生成（本命の価値） | ほぼ無し（誤字の最終微修正のみ） |
| **見た目（スタイル）** | スタイルを config で一元管理し、①ASS/焼き込みに反映 ②推奨インスペクタ値を文書化 | 保存済みトラックプリセットを **1回**当てる |
| **確認** | 焼き込み mp4 プレビューを生成 | 完成品として確認 |

→ **SRT を主成果物**とし、スタイルは「Resolve のトラックプリセット＋文書化した推奨値」で担保する。ASS と焼き込みは「スタイルを可視化・検証する補助成果物」と位置づける（Resolve は ASS 装飾を無視する点を明記）。

### 1.3 日本語字幕の整形基準（調査で確認した目安）
- **1行の文字数**: 全角 **13〜14字**前後（横1080p基準）。
- **行数**: 最大 **2行**。
- **表示時間**: 最大 **6〜6.5秒**、下限も設ける（短すぎ segment を結合）。
- **読み速度**: 1秒あたり **4文字**（翻訳字幕の密度基準。同一言語の一人喋りはもう少し速くても可 → パラメータ化）。
- **句読点**: 「読点は半角アキ／句点は全角アキ」で置く流儀（映画式）と、そのまま残す流儀（YouTube式）がある → **モード選択制**にする。
- **配置/サイズ**: セーフエリア下寄せ、フォント高さ **約9%**。白文字＋黒縁（縁取り太さ 5〜6・外側）＋帯（黒・不透明度 **70%**）＋影（最小）の優先順で視認性を出すのがセオリー。

---

## 2. 出力物の全体像

`--format` に字幕系を追加（既存の txt/json はそのまま）。

| 形式 | 内容 | 主な用途 |
|------|------|---------|
| `srt` | 整形済み字幕（連番・`,`区切り） | **DaVinci 取り込みの本命** |
| `vtt` | WebVTT（`.`区切り） | Web/YouTube |
| `ass` | スタイル込み字幕（フォント/色/帯/縁/位置） | 焼き込み・他プレイヤー。※Resolve は装飾無視 |
| `txt` | 時刻つき/なし（既存を拡張済み） | 確認・台本 |
| `json` | segment＋**word 単位**時刻（拡張） | 再処理・解析 |
| `mp4`(preview) | 焼き込みプレビュー（ffmpeg） | 見た目/タイミング検証 |

補助: `docs/davinci-workflow.md`（編集者向け手順）＋ 推奨インスペクタ設定値。

---

## 3. アーキテクチャ

既存の疎結合設計（`core/` ＋ `output/`、Backend 抽象、writer ディスパッチ）を踏襲して拡張する。

### 3.1 新規モジュール
```
src/transcripter/
├── core/
│   └── subtitle/
│       ├── model.py         # Word, Cue（字幕1枚）データ型
│       ├── reflow.py        # words → cue 整形エンジン（本機能の核）
│       ├── postprocess.py   # フィラー除去・用語/表記辞書置換（word対応）
│       └── style.py         # SubtitleStyle（見た目）＋既定値＋ASS/ffmpeg変換
│   └── burnin.py            # ffmpeg 焼き込みプレビュー（任意）
└── output/
    ├── srt.py               # Cue[] → SRT
    ├── vtt.py               # Cue[] → VTT
    └── ass.py               # Cue[] + SubtitleStyle → ASS
```

### 3.2 既存への変更点
- `core/backend.py`: `Word` を追加し、`Segment.words: list[Word]`（任意）を持たせる。
- `core/faster_whisper_backend.py`: `word_timestamps=True` 時に `seg.words` を `Word` に写す。
- `core/transcriber.py`: 字幕系フォーマット要求時に **word_timestamps を自動有効化**し、reflow→writer へ流す。
- `output/writer.py`: `EXTENSIONS`/ディスパッチに `srt`/`vtt`/`ass` を登録。
- `config.py`: `SUPPORTED_FORMATS` に `srt,vtt,ass` を追加（**現状は txt/json 以外を弾くため、これが無いと `--format srt` がエラー**）。`[subtitle]` セクションと `SubtitleStyle` の読み込みを追加。
- `cli.py`: 字幕関連オプション追加（§7）。
- `output/timefmt.py`: 既存の `format_timestamp(sep=",")/(".")` を SRT/VTT/ASS で共用（ASS は `H:MM:SS.cc` の 1/100 秒なので専用整形を1つ追加）。

### 3.3 データフロー
```
音声/動画 → ffmpeg(16k/mono) → faster-whisper(word_timestamps=True, vad)
  → Segment[](words) → postprocess(フィラー除去・辞書置換)
  → reflow(パラメータ) → Cue[]
  → writer: srt / vtt / ass / txt / json
  → (任意) burnin: ffmpeg で mp4 プレビュー
```

---

## 4. 字幕整形エンジン（reflow）仕様

**本機能の中核**。Whisper の segment は字幕には長すぎ/短すぎるため、word 単位時刻を使って**字幕1枚（cue）に再分割**する。

### 4.1 アルゴリズム（word 列 → cue 列）
1. **境界検出で分割**: 次のいずれかで cue を切る。
   - 直前 word との**無音ギャップ ≥ `gap_split_s`**。
   - 文末/句読点（`。！？` など、`split_on_punctuation`）。
   - **累積文字数が `max_chars_per_cue` に到達**。
2. **最小/最大表示時間の補正**:
   - cue 長 < `min_duration_s` → 次 cue と結合、または末尾を延長（次 cue の開始までクランプ）。
   - cue 長 > `max_duration_s` → 文字/ポーズ境界でさらに分割。
   - **読み速度**: 文字数/長さ > `max_cps` なら表示時間を延長（可能なら）。
3. **行分割（最大2行）**: cue 内テキストを `max_chars_per_line` 以下で改行。
   - 改行位置は**句読点・助詞境界を優先**（`balanced`＝2行の長さを均す / `greedy`）。
4. **word 時刻が無い場合**（`word_timestamps=False`）: segment 単位でだけ分割（文字数と時間のみ、精度は落ちる）。フォールバックとして機能させる。

### 4.2 パラメータ（config `[subtitle]` / CLI）
| キー | 既定 | 説明 |
|------|------|------|
| `max_chars_per_line` | `14` | 1行の最大全角文字数 |
| `max_lines` | `2` | 最大行数 |
| `max_chars_per_cue` | `28` | 字幕1枚の最大文字数（= line×lines 目安） |
| `min_cue_chars` | `3` | これ未満の極小 cue は時間的に近い隣へ結合 |
| `min_duration_s` | `1.2` | 最短表示秒（短すぎ segment を結合） |
| `max_duration_s` | `6.0` | 最長表示秒 |
| `max_cps` | `13` | 1秒あたり最大文字数（読み速度。翻訳字幕基準は 4、一人喋りは緩め） |
| `gap_split_s` | `0.8` | この秒数以上の無音で cue を切る |
| `split_on_punctuation` | `true` | 句読点で cue を切る |
| `line_break` | `balanced` | 改行戦略 `balanced`/`greedy` |
| `punctuation_mode` | `keep` | `keep`（残す）/`space`（読点=半角アキ,句点=全角アキ）/`drop`（除去）|
| `strip_fillers` | `false` | フィラー除去の ON/OFF |
| `filler_words` | 内蔵リスト | 「えー/あの/まあ/その/なんか…」等（config で上書き） |
| `term_dictionary` | `""` | 表記/誤変換の置換CSV（`引地` ルールを流用可） |

### 4.3 後処理（postprocess）
- **用語・表記辞書**: `誤→正` のCSV置換（word をまたぐ表現も対応）。**既存の話者名修正（引き地→引地 等）はここに統合**し、字幕にも自動適用する。
- **フィラー除去**: `strip_fillers=true` 時、行頭/単独のフィラー word を落とす（意味語は残す保守的既定）。

---

## 5. スタイルモデル（テロップの見た目）

config `[subtitle.style]` で一元管理し、**ASS 出力 / ffmpeg 焼き込み / Resolve 推奨値の文書化**の3つに反映する。

### 5.1 既定値（1080p 横・白文字＋黒縁＋帯、調査のセオリー準拠）
| キー | 既定 | 説明 |
|------|------|------|
| `font_family` | `Noto Sans JP` | ゴシック（帯なら明朝も可）。端末に無い場合の代替も明記 |
| `font_bold` | `true` | 太字 |
| `font_size_pct` | `9.0` | フレーム高に対する % |
| `text_color` | `#FFFFFF` | 文字色（白） |
| `outline` | `true` | 縁取り ON |
| `outline_color` | `#000000` | 縁色（黒） |
| `outline_width` | `6` | 縁の太さ（Resolve 値目安 5〜6 / ASS では ~3 に換算） |
| `box` | `false` | 帯（背景）ON/OFF。既定は縁取りのみ、帯は任意 |
| `box_color` | `#000000` | 帯の色 |
| `box_opacity` | `70` | 帯の不透明度 %（スマホ視認性の基準） |
| `shadow` | `2` | 影（最小）。0 で無効 |
| `position` | `bottom` | `bottom`/`top` |
| `margin_v_pct` | `10.0` | 下（上）マージン（セーフエリア） |
| `alignment` | `center` | 水平位置 |

### 5.2 反映先マッピング
- **ASS**: `[V4+ Styles]` の 1 スタイル行に変換（`Fontname/Fontsize/PrimaryColour/OutlineColour/BackColour/Outline/Shadow/Alignment/MarginV`、色は `&HAABBGGRR`）。
- **焼き込み(ffmpeg)**: `subtitles=sub.srt:force_style='...'` もしくは `ass=sub.ass`。
- **Resolve**: インスペクタ推奨値として `docs/davinci-workflow.md` に表で記載し、**保存プリセット名**（例: `telop_white_outline_v1`）を運用で共有。

---

## 6. DaVinci Resolve 連携ワークフロー（編集者向け）

1. 本ツールで `--format srt`（＋確認用に `--format mp4` プレビュー）を生成。
2. Resolve のメディアプールへ `.srt` をドラッグ → 字幕トラック ST1 生成。
3. ST1 を選択 → インスペクタで**保存済みトラックプリセット**を適用（初回のみ手動設定→プリセット保存）。
4. 焼き込みプレビューと見比べ、誤字と改行だけ微修正。
5. （任意・上級）Resolve Studio なら Python スクリプトで SRT 取り込みまで自動化（§9 Phase C）。

---

## 7. CLI / config 追加仕様

```bash
# 字幕（segment/word 自動）＋確認プレビュー
transcripter transcribe talk.mp4 --format srt,mp4 --vad

# スタイル込み ASS も同時に
transcripter transcribe trip.mov --format srt,ass --vad --strip-fillers

# 整形パラメータ上書き
transcripter transcribe talk.mp4 --format srt \
  --sub-max-line-chars 13 --sub-max-lines 2 --sub-max-duration 6 --sub-gap-split 0.8
```

追加オプション（すべて config `[subtitle]`/`[subtitle.style]` にも対応、優先順位: CLI > config > 既定）:
`--word-timestamps/--no-word-timestamps`（既定: 字幕系フォーマット時に自動 on）、
`--sub-max-line-chars`、`--sub-max-lines`、`--sub-max-chars`、`--sub-min-duration`、`--sub-max-duration`、`--sub-max-cps`、`--sub-gap-split`、`--sub-line-break {balanced,greedy}`、`--sub-punctuation {keep,space,drop}`、`--strip-fillers`、`--term-dict PATH`、`--preview`（=mp4 焼き込み）、`--sub-style PATH`（スタイルtoml）。

---

## 8. 焼き込みプレビュー（burn-in）

- `ffmpeg -i input.mp4 -vf "subtitles=out.srt:force_style='FontName=Noto Sans JP,FontSize=...,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=3,BorderStyle=1'" -c:a copy preview.mp4`
- 帯を出す場合は `BorderStyle=3`（塗り背景）＋ `BackColour`。ASS 経由（`ass=out.ass`）ならスタイル一括。
- 目的は**見た目・タイミング・改行の一括検証**。処理は任意（`--preview` 時のみ）。長尺は時間がかかる旨を明記。

---

## 9. フェーズ分割と実装タスク

### Phase A — 字幕の中核（実装済み）
- [x] `core/subtitle/model.py`（`Cue`）、`core/backend.py` に `Word`/`Segment.words` 追加
- [x] `faster_whisper_backend.py` の `word_timestamps` 反映、`transcriber.py` で字幕系フォーマット時に自動有効化
- [x] `core/subtitle/reflow.py`（§4 アルゴリズム＋パラメータ＋極小cueマージ）
- [x] `core/subtitle/postprocess.py`（辞書置換＝**引地ルール流用可**、フィラー除去）
- [x] `output/srt.py` / `output/vtt.py`、writer ディスパッチ登録、`config.SUPPORTED_FORMATS` 拡張
- [x] `config.py` `[subtitle]` 読み込み、CLI オプション、README 更新
- [x] テスト（§10）— reflow/writer/style/config 計55件

### Phase B — スタイルとプレビュー（実装済み）
- [x] `core/subtitle/style.py`（`SubtitleStyle`＋ASS/ffmpeg 変換）、`output/ass.py`
- [x] `core/burnin.py`（ffmpeg 焼き込み、`--preview`。4K/高fps 素材向けにダウンスケール）
- [x] `docs/davinci-workflow.md`（推奨インスペクタ値＋プリセット運用）、`config.example.toml` に `[subtitle.style]`

### Phase C — 高度化（実装済み）
- [x] **形態素解析による語境界改行**（fugashi→janome→sudachi 自動検出、未導入時は禁則ヒューリスティックにフォールバック。`--extra morph` / `--sub-morph`）
- [x] **禁則処理**（行頭の小書き仮名・句読点・閉じ括弧を回避）＋小書き仮名始まりの語を cue 途中で切らない
- [x] **スタイルプリセット**（`outline`/`box`/`cinema`。`--sub-preset` / `[subtitle.style].preset`）
- [x] **Resolve 取り込みスクリプト**（`scripts/davinci_import_srt.py`・Studio 前提の best-effort）
- [x] **WhisperX バックエンド**（forced alignment で単語±50ms。`--backend whisperx` / `--extra whisperx`。任意・重い）
- [x] **話者ラベル**（pyannote 話者分離→ cue へ話者付与・話者変化で分割。`--diarize` ＋ HF トークン、`--speaker-labels`）
- [x] **ローカル GUI**（FastAPI ドラッグ&ドロップ。`transcripter serve` / `--extra webui`）

> 注: WhisperX / pyannote は実機・モデルDL・HFトークンが要るため CI/単体テスト対象外
> （コード経路・話者ラベルの整形は mock でテスト）。GUI はページ配信を smoke test 済み。

---

## 10. テスト方針
- **reflow**（最重要）: 文字数上限での改行、cue 分割（ギャップ/句読点/文字数）、min/max 表示時間の補正、max_cps、balanced 改行、word 無し時のフォールバック。
- **writer**: SRT（連番/空行/`,`）、VTT（`WEBVTT`/`.`）、ASS（スタイル行・`&HAABBGGRR` 色変換）のスナップショット。
- **timefmt**: 既存の境界値テスト（0/59.999/1h超/丸め）を ASS の 1/100 秒整形にも拡張。
- **postprocess**: 辞書置換（引地ルール）、フィラー除去、word またぎ置換。
- **結合**: word 付き Segment をモック生成 → reflow → 各 writer の end-to-end（モデル DL 不要）。
- **style→ass/ffmpeg**: 色・不透明度・縁・帯・位置のマッピング一致。

---

## 11. 決定事項（確定済み・実装反映）
1. ✅ **着手範囲**: Phase A / B を実装 → その後 Phase C も全項目実装（WhisperX・話者ラベル・GUI）。
2. ✅ **句読点モード既定**: `keep`（YouTube式・残す）。`--sub-punctuation` で `space`/`drop` に変更可。
3. ✅ **帯（背景）の既定**: 「白文字＋黒縁のみ（box=false）」を既定に採用。帯は `--sub-box`／`preset=box` で有効化。
4. ✅ **フィラー除去の既定**: 既定 off（`--strip-fillers` で on）。
5. ✅ **ASS/焼き込みの優先度**: Phase B として即実装済み（ASS 出力＋ffmpeg 焼き込みプレビュー）。

---

## 12. 参照

**DaVinci Resolve / 字幕スタイル**
- SRT→帯・縁の作り方（インスペクタ設定・不透明度70%・縁5〜6）: https://note.com/marumarutelop/n/nf4a1e4191987
- 字幕トラックをプリセット保存/再利用（Blackmagic Forum / チュートリアル）: https://forum.blackmagicdesign.com/viewtopic.php?f=36&t=160019 , https://www.youtube.com/watch?v=I8Ncce57nLg
- ASS vs SRT（Resolve は ASS 装飾を無視・SRT 変換が定石）: https://subtitleops.com/blog/ass-vs-srt-when-to-convert , https://editingtools.io/guides/convert-ass-to-resolve-subtitle
- Resolve 字幕インポート公式マニュアル: https://www.steakunderwater.com/VFXPedia/__man/Resolve18-6/DaVinciResolve18_Manual_files/part1280.htm

**Claude Code × Whisper / DaVinci 自動化の先例**
- Claude Code × Whisper で SRT 自動生成: https://note.com/roomaime/n/nf426600054cc
- Claude Code で DaVinci Resolve を自動操作（Lua/Python・無料版はAPI制限）: https://www.aquallc.jp/claude-code-davinci-resolve/
- Claude Code 動画編集シリーズ（Whisper→SRT 第4回）: https://octomblog.com/docs/concepts_claude-code-video-editing_04/
- 動画編集の完全自動化（無音カット×テロップ×Bロール）: https://rutinelabo.com/claudecode-video-editing-automation/
- テロップ入れプラグイン AutoTitles: https://note.com/ikmsan/n/n98316a91f80d

**字幕整形アルゴリズム / 日本語基準**
- faster-whisper で SRT を「いい感じ」に（word時刻・ギャップ3s・最大48字・24字改行・辞書置換）: https://zenn.dev/mossan_hoshi/articles/20241011_faster_whisper_srt
- Whisper で字幕（Monstarlab）: https://engineering.monstar-lab.com/jp/post/2023/12/08/Subtitling-with-Whisper/
- 日本語字幕の基準（1秒4文字・1行13字・最大6.5秒・2行）: https://vook.vc/n/1339 , https://translations.ted.com/TED_%E6%97%A5%E6%9C%AC%E8%AA%9E%E5%AD%97%E5%B9%95%E3%81%AE%E8%A1%A8%E8%A8%98%E3%82%AC%E3%82%A4%E3%83%89%E3%83%A9%E3%82%A4%E3%83%B3

**基盤（既存 SPEC より）**
- faster-whisper README（word_timestamps/vad）: https://github.com/SYSTRAN/faster-whisper/blob/master/README.md
- WhisperX（forced alignment）: https://github.com/m-bain/whisperX
- WebVTT 仕様: https://www.w3.org/TR/webvtt1/ / ASS(SubStation Alpha) タグ仕様（各所）
