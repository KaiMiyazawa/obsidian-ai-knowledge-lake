"""入力ファイルの収集。

ファイル・ディレクトリ（複数可）を受け取り、対象拡張子のファイル一覧へ展開する。
音声/動画（transcribe）でも PDF（pdf）でも、拡張子集合を差し替えるだけで使い回せる。
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .core.audio import SUPPORTED_EXTS
from .logging_conf import get_logger

logger = get_logger()


def collect_inputs(
    paths: list[Path],
    exts: Iterable[str] | None = None,
    recursive: bool = False,
) -> list[Path]:
    """入力パス群を対象ファイルのリストに展開する（重複排除・ソート済み）。

    Args:
        paths: ファイル/ディレクトリのパス（複数可）。
        exts: 対象拡張子の集合（小文字・ドット付き、例 {".pdf"}）。
            None の場合は音声/動画の既定集合を使う。
        recursive: ディレクトリを再帰探索するか。

    - ファイル: 対象拡張子ならそのまま採用、対象外なら警告してスキップ。
    - ディレクトリ: 直下（recursive=True なら再帰）の対象ファイルを採用。
    """
    target = {e.lower() for e in (exts if exts is not None else SUPPORTED_EXTS)}

    def _match(path: Path) -> bool:
        return path.suffix.lower() in target

    found: list[Path] = []
    for p in paths:
        p = p.expanduser()
        if not p.exists():
            logger.warning("入力が存在しません（スキップ）: %s", p)
            continue
        if p.is_file():
            if _match(p):
                found.append(p)
            else:
                logger.warning(
                    "対象外の拡張子（スキップ）: %s（対象: %s）",
                    p.name, ", ".join(sorted(target)),
                )
        elif p.is_dir():
            pattern = "**/*" if recursive else "*"
            matched = [c for c in p.glob(pattern) if c.is_file() and _match(c)]
            if not matched:
                logger.warning("対象ファイルが見つかりません: %s", p)
            found.extend(matched)

    # 重複排除（順序安定）+ ソート
    unique = sorted({f.resolve() for f in found})
    return unique
