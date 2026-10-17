"""pymupdf4llm バックエンド（既定）。

テキスト層を直読して Markdown 化する軽量・ローカル・GPU不要のエンジン。
デジタル PDF（テキスト埋め込み）に最適で、日本語・表の再現が良好。
スキャン画像 PDF には弱いので、その場合は docling バックエンドを使う。
"""

from __future__ import annotations

from pathlib import Path

from ...errors import PdfConversionError
from ...logging_conf import get_logger

logger = get_logger()


class PyMuPDF4LLMBackend:
    """pymupdf4llm による PdfBackend 実装。"""

    name = "pymupdf4llm"

    def convert(self, pdf_path: Path) -> str:
        # 重い import は変換時まで遅延
        try:
            import pymupdf4llm
        except ImportError as exc:  # pragma: no cover
            raise PdfConversionError(
                "pymupdf4llm がインストールされていません。"
                "`uv sync` または `pip install pymupdf4llm` を実行してください。"
            ) from exc

        logger.debug("pymupdf4llm で変換: %s", pdf_path)
        try:
            md = pymupdf4llm.to_markdown(
                str(pdf_path),
                page_chunks=False,
                show_progress=False,
            )
        except Exception as exc:  # noqa: BLE001 - ライブラリ例外を集約
            raise PdfConversionError(
                f"PDF 変換に失敗しました: {pdf_path.name}: {exc}"
            ) from exc

        if not isinstance(md, str):  # 念のための型ガード
            md = str(md)
        return md
