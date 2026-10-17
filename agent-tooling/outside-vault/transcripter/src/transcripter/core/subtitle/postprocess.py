"""字幕テキストの後処理: 用語/表記辞書の置換とフィラー除去。

- 用語辞書: `誤,正` の CSV（1 行 1 ペア、`#` 始まりはコメント）。
  cue のテキストに対して単純置換。話者名修正（例: 引き地→引地）もここで扱う。
- フィラー: 単独の相槌・言いよどみ（えー/あの/まあ 等）を word 単位で落とす。
"""

from __future__ import annotations

import csv
from pathlib import Path

# 保守的な既定フィラー。strip_fillers=True のときのみ適用。
DEFAULT_FILLERS: tuple[str, ...] = (
    "えー", "えーと", "えっと", "あー", "あのー", "あの", "そのー",
    "まあ", "まぁ", "なんか", "ええと", "うーん", "んー",
)

# フィラー比較時に無視する末尾記号。
_TRIM_CHARS = "、。,.！!？? 　"


def load_term_map(path: str | Path) -> list[tuple[str, str]]:
    """置換辞書 CSV を読み込む。列は [誤, 正]。順序を保持して返す。"""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"用語辞書が見つかりません: {p}")
    pairs: list[tuple[str, str]] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            src = row[0].strip()
            if not src or src.startswith("#"):
                continue
            dst = row[1].strip() if len(row) > 1 else ""
            pairs.append((src, dst))
    return pairs


def apply_term_map(text: str, term_map: list[tuple[str, str]]) -> str:
    """辞書ペアを順に置換する（word をまたぐ表現にも対応）。"""
    for src, dst in term_map:
        if src:
            text = text.replace(src, dst)
    return text


def is_filler(word_text: str, fillers: set[str]) -> bool:
    """word（前後の記号・空白を除く）がフィラーそのものか。"""
    core = word_text.strip().strip(_TRIM_CHARS)
    return bool(core) and core in fillers


def humanize_speaker(label: str | None) -> str:
    """pyannote の 'SPEAKER_00' を '話者1' のように読みやすくする。"""
    if not label:
        return ""
    if label.upper().startswith("SPEAKER_"):
        num = label.split("_")[-1]
        try:
            return f"話者{int(num) + 1}"
        except ValueError:
            return label
    return label


def apply_punctuation_mode(text: str, mode: str) -> str:
    """句読点の扱い。

    keep:  そのまま
    space: 読点=半角アキ / 句点=全角アキ（映画字幕式）
    drop:  読点・句点を除去
    """
    if mode == "keep":
        return text
    if mode == "drop":
        return text.replace("、", "").replace("。", "")
    if mode == "space":
        return text.replace("、", " ").replace("。", "　").rstrip("　 ")
    return text
