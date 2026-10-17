# todo.md — 字幕付与（タイムスタンプ）機能の設計と実装計画

> ⚠️ **このファイルは初期メモです。正式な設計・実装計画は
> [`docs/subtitle-telop-plan.md`](docs/subtitle-telop-plan.md) に移行しました**
> （DaVinci Resolve 連携・テロップ整形エンジン・スタイル・調査結果を反映）。
> 以下は SRT/VTT 出力フォーマットの技術メモとして残す。矛盾する場合は plan を優先。
>
> 本ファイルは「字幕付与（時刻つき出力: SRT/VTT、および時刻つき TXT）」の設計メモ。
> MVP（Phase 1）では **時刻なしの単純トランスクリプト（.txt）** を先に実装する。
> 本機能はその後続（Phase 1.5）として実装する。SPEC.md と整合させること。

---

## 0. 前提・確定方針

- 実行環境: **Apple Silicon Mac**、NVIDIA GPU なし → `device=cpu` / `compute_type=int8`。
- 推論バックエンド: **faster-whisper（turbo）**。
- 既定言語: `ja`。
- 字幕付与は「単純トランスクリプト」とは出力形式が違うだけで、推論パイプラインは共通化する。

---

## 1. ゴール

入力音声/動画から、時刻つきの字幕ファイルを生成する。

- `.srt`（SubRip）
- `.vtt`（WebVTT）
- 時刻つき `.txt`（`[HH:MM:SS] テキスト` 形式、任意）
- `.json`（segment の start/end/text、将来は word 単位も）

---

## 2. 時刻情報の取得方法

faster-whisper の `transcribe()` は segment ごとに `start` / `end`（秒, float）を返す。
これをそのまま字幕の表示区間に使う（segment 単位字幕）。

```python
segments, info = model.transcribe(
    audio,
    language="ja",
    vad_filter=True,            # 字幕では無音除去が効く（区切りが自然に）
    word_timestamps=False,      # 段階1は segment 単位。段階2で True
)
for seg in segments:
    seg.start  # 秒
    seg.end    # 秒
    seg.text
```

### 段階1: segment 単位（まず実装）
- faster-whisper の segment の start/end をそのまま使う。
- 追加依存ゼロ。turbo + CPU で動く。
- 精度は ±数百ms 程度（Whisper 標準）。一般的な字幕には十分。

### 段階2: word 単位（精度向上、任意）
- `word_timestamps=True` で `seg.words[*].start/end` を取得。
- 行を細かく割れる／カラオケ字幕的にもできる。
- さらに高精度（±50ms）が要るなら WhisperX の forced alignment を Phase 3 で検討（依存増）。

---

## 3. 時刻フォーマッタ仕様

秒(float) → タイムコード文字列。SRT と VTT で**区切り文字が違う**点に注意。

| 形式 | 例 | ミリ秒区切り |
|------|-----|------------|
| SRT  | `00:01:23,456` | カンマ `,` |
| VTT  | `00:01:23.456` | ピリオド `.` |

```python
def format_timestamp(seconds: float, *, sep: str) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"
# SRT: sep=","  /  VTT: sep="."
```

エッジケース:
- `start == end`（極短 segment）→ 最小表示時間（例 500ms）を確保する補正を入れるか検討。
- 負値/NaN ガード。
- segment が時間的に重なる場合の扱い（基本そのまま、必要なら end を次の start にクランプ）。

---

## 4. 出力フォーマット仕様

### 4.1 SRT
```
1
00:00:00,000 --> 00:00:03,200
こんにちは

2
00:00:03,200 --> 00:00:06,500
今日はいい天気ですね
```
- 1始まりの連番インデックス。
- ブロック間は空行。
- 文字コード UTF-8（BOM なし。プレイヤー互換のため BOM 付きオプションも検討）。

### 4.2 VTT
```
WEBVTT

00:00:00.000 --> 00:00:03.200
こんにちは

00:00:03.200 --> 00:00:06.500
今日はいい天気ですね
```
- 先頭に `WEBVTT` + 空行。
- インデックスは任意（省略可）。

### 4.3 時刻つき TXT（任意）
```
[00:00:00] こんにちは
[00:00:03] 今日はいい天気ですね
```
- 既存の時刻なし txt ライタに「時刻プレフィックス」オプションを足す形で実装。

### 4.4 JSON
- 既存 json 出力に `start`/`end`（既に保持）を含むので追加実装ほぼ不要。
- 段階2で `words` 配列を追加。

---

## 5. 字幕の読みやすさ整形（Phase 2〜3、任意）

Whisper の segment は長すぎ/短すぎることがある。字幕品質のため以下を検討。

- **最大文字数/行**（日本語の目安: 全角 ~20字、最大2行）。
- **最大表示時間**（例 ~6秒）／**最小表示時間**（例 ~1秒）。
- **改行ルール**: 句読点（、。）や助詞境界で折り返し。
- 長い segment の分割（word_timestamps があると自然に割れる）。
- 連続する無音の除去（VAD と連動）。

→ まずは「segment をそのまま SRT/VTT 化」。整形は後続でオプション化（`--subtitle-max-chars` 等）。

---

## 6. CLI への追加（SPEC §13 と整合）

字幕は既存の `--format` に乗せるだけ。新規サブコマンドは作らない。

```bash
# 字幕生成（segment 単位）
transcripter input.mp4 --format srt --vad

# 複数形式同時
transcripter input.mp3 --format srt,vtt,json

# 時刻つき txt
transcripter input.mp3 --format txt --timestamps
```

追加オプション（後続）:
| オプション | 既定 | 説明 |
|-----------|------|------|
| `--word-timestamps` | off | 段階2: word 単位タイムスタンプ |
| `--subtitle-max-chars` | なし | 1行あたり最大文字数（整形） |
| `--subtitle-max-duration` | なし | 1字幕の最大表示秒 |
| `--srt-bom` | off | SRT を BOM 付き UTF-8 で出力 |

---

## 7. 実装タスク（チェックリスト）

### Phase 1.5: 基本字幕（segment 単位）
- [ ] `format_timestamp(seconds, sep)` 実装（SRT/VTT 共用）
- [ ] `output/srt.py`: segment 配列 → SRT 文字列
- [ ] `output/vtt.py`: segment 配列 → VTT 文字列
- [ ] `output/txt.py` に `--timestamps` プレフィックス対応を追加
- [ ] writer ディスパッチに srt/vtt を登録（`--format srt,vtt` で動く）
- [ ] VAD 既定 on を字幕時に推奨（区切り改善）— 既定値の検討
- [ ] 単体テスト: 時刻整形（境界値: 0, 59.999s, 1h超, ミリ秒丸め）、SRT/VTT スナップショット
- [ ] エッジケース: start==end の最小表示時間補正、重なり処理

### Phase 2: word 単位
- [ ] `word_timestamps=True` 連携
- [ ] JSON に `words` 追加
- [ ] word 境界での行分割（任意整形）

### Phase 3: 高精度・整形
- [ ] WhisperX forced alignment 連携（±50ms、依存増）
- [ ] 字幕整形ルール（最大文字数/行数/表示時間、句読点改行）
- [ ] 話者分離ラベルを字幕に付与（pyannote）

---

## 8. テスト観点

- 時刻フォーマッタ: 0秒 / 1時間超 / ミリ秒丸め（四捨五入）/ SRT・VTT の区切り差。
- SRT: 連番、空行、UTF-8。
- VTT: `WEBVTT` ヘッダ、区切り `.`。
- 実音声（短尺 ja/en fixture）で segment 時刻が単調増加すること。
- 既存 txt（時刻なし）と時刻つき txt の切替が `--timestamps` で正しく効くこと。

---

## 9. 参照

- faster-whisper README（segment.start/end, word_timestamps, vad_filter）: https://github.com/SYSTRAN/faster-whisper/blob/master/README.md
- openai-whisper の SRT/VTT 出力（Discussion #911）: https://github.com/openai/whisper/discussions/911
- WhisperX（forced alignment, 単語±50ms）: https://github.com/m-bain/whisperX
- WebVTT 仕様: https://www.w3.org/TR/webvtt1/
