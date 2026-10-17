"""Markdown 出力ライタ（PDF → md 用）。

出力先は output_dir、無ければ入力 PDF と同じディレクトリ。
既存ファイルは overwrite=False ならスキップ。
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

from ..logging_conf import get_logger

logger = get_logger()

# PDF の文字抽出では、部首用の別コードの文字（⽇⽉⻑ など）や中黒の別字が混ざり、
# 見た目は同じでも検索・grep にヒットしなくなる。NFKC で康熙部首は直り、
# NFKC で直らない CJK 部首補助（⻑ など）と中黒だけ個別に置換する。
_EXTRA_MAP = str.maketrans(
    {
        "⻑": "長", "⻄": "西", "⻘": "青", "⻩": "黄", "⻭": "歯", "⻯": "竜", "⻲": "亀",
        "‧": "・", "･": "・",
    }
)


def normalize_pdf_text(text: str) -> str:
    """PDF 抽出テキストの互換文字を通常の字形へ寄せる（NFKC＋個別置換）。"""
    return unicodedata.normalize("NFKC", text).translate(_EXTRA_MAP)


def write_markdown(
    markdown: str,
    input_path: Path,
    output_dir: Path | None,
    *,
    overwrite: bool = False,
) -> Path | None:
    """Markdown を `<入力名>.md` として書き出す。

    Returns:
        書き出したパス。スキップした場合は None。
    """
    base_dir = output_dir or input_path.parent
    base_dir.mkdir(parents=True, exist_ok=True)
    out_path = base_dir / f"{input_path.stem}.md"

    if out_path.exists() and not overwrite:
        logger.warning("既存のためスキップ: %s（--overwrite で上書き）", out_path)
        return None

    markdown = normalize_pdf_text(markdown)
    content = markdown if markdown.endswith("\n") else markdown + "\n"
    out_path.write_text(content, encoding="utf-8")
    logger.info("出力: %s", out_path)
    return out_path
