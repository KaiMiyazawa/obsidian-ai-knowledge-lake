"""PDF 変換バックエンドの抽象インターフェース。

CLI / converter 層はこの Protocol にのみ依存する。
将来 docling 以外（marker 等）を足す場合もここに合わせるだけでよい。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PdfBackend(Protocol):
    """PDF → Markdown 変換バックエンド。"""

    #: バックエンド名（ログ表示・選択用）
    name: str

    def convert(self, pdf_path: Path) -> str:
        """1 つの PDF を Markdown 文字列に変換して返す。

        Raises:
            PdfConversionError: 変換に失敗した場合。
        """
        ...
