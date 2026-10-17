# DaVinci Resolve 連携ワークフロー（編集者向け）

transcripter が生成した字幕を DaVinci Resolve に取り込み、**微修正だけ**で仕上げる手順。
背景と設計判断は [`subtitle-telop-plan.md`](subtitle-telop-plan.md) を参照。

## 前提（重要）
- **DaVinci は SRT を確実に取り込む**が、**ASS の装飾はほぼ無視**する。
- したがって Resolve では **SRT を使い、見た目はインスペクタでトラックに適用**する。
  一度作った見た目は **トラックプリセットとして保存**し、次回以降は 1 クリックで再現する。
- `.ass` と焼き込み `_preview.mp4` は **見た目・タイミングの確認用**（Resolve には持ち込まない）。

## 生成
```bash
# 字幕（SRT）＋確認用の焼き込みプレビュー
uv run transcripter transcribe trip.mp4 --format srt --vad --preview

# スタイル確認用に ASS も出す場合
uv run transcripter transcribe trip.mp4 --format srt,ass --vad --preview
```
出力: `trip.srt`（本命）／`trip.ass`（任意）／`trip_preview.mp4`（確認用・既定1080p30）。

## Resolve での手順
1. `trip.srt` をメディアプールへドラッグ → 字幕トラック **ST1** が生成される。
2. `_preview.mp4` を見ながら、誤字・改行だけ修正（テキストは SRT 側で直して再取り込みでも可）。
3. ST1 のクリップを選択 → インスペクタで見た目を設定（初回のみ）。下表を基準にする。
4. 設定後、字幕クリップ選択 → Video タブの「…」→ **「トラックをプリセットとして保存」**
   （例: `telop_white_outline_v1`）。次回からはこのプリセットを当てるだけ。

## インスペクタ推奨値（白文字＋黒縁・1080p 基準）
> transcripter の ASS 既定と揃えた値。Resolve の「縁取り」尺度は ASS と異なるため、
> Resolve では 5〜6 程度が本ツールの Outline=3 に相当。

| 項目 | 推奨値 | 備考 |
|------|--------|------|
| フォント | Noto Sans JP（Bold） | ゴシック。端末に無ければ他のゴシック体 |
| サイズ | フレーム高の約 9%（1080p で 約96px） | スマホ視認性 |
| 文字色 | 白 #FFFFFF | |
| 縁取り（ストローク） | 黒・太さ 5〜6・**外側** | 最優先の視認性要素 |
| 背景（帯） | 任意（既定 OFF）。使うなら黒・**不透明度 70%** | 屋外/明るい背景で有効 |
| 影（ドロップシャドウ） | 最小（ぼかし2／距離2）または OFF | 補助 |
| 配置 | 下寄せ・セーフエリア内（下マージン約10%） | |
| 行 | 最大2行／1行あたり約14全角字 | transcripter 側で整形済み |

視認性の効かせ方の優先順は「**白文字 ＞ 黒縁 ＞ 帯 ＞ 影**」。

## 帯（背景）付きにしたいとき
本ツール側でも帯付きプレビューを出せる（見た目確認用）:
```bash
uv run transcripter transcribe trip.mp4 --format srt,ass --preview --sub-box --sub-box-opacity 70
```
Resolve 側では上表の「背景（帯）」を ON にして同じ見た目を再現する。

## 上級: Resolve Studio でのスクリプト取り込み
`scripts/davinci_import_srt.py` を Resolve（Studio 推奨）内の Console / スクリプトメニュー、
または端末から実行すると、SRT のメディアプール取り込みを自動化できる。
```bash
python scripts/davinci_import_srt.py /path/to/video.srt
```
> Resolve のバージョンにより字幕インポートAPIの挙動が異なる。失敗時は手動取り込み
> （メディアプールへドラッグ / File > Import > Subtitle）にフォールバックすること。
> 見た目のトラックプリセット適用は上表に沿って手動で行う（＝1クリック運用）。
> 本スクリプトは Resolve 実機が必要なため transcripter のテスト対象外。
