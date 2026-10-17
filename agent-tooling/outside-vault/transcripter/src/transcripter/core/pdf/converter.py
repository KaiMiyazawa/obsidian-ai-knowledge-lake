"""PDF → Markdown 変換のオーケストレーション。

バックエンドの生成と、1 ファイル分の「変換 → 出力」をまとめる。
失敗は送出せず PdfOutcome に集約し、バッチ継続できるようにする。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...errors import PdfConversionError
from ...logging_conf import get_logger
from ...output.markdown_writer import write_markdown
from .backend import PdfBackend

logger = get_logger()


def make_backend(name: str) -> PdfBackend:
    """バックエンド名から実装を生成する。

    Raises:
        PdfConversionError: 未対応の名前。
    """
    if name == "pymupdf4llm":
        from .pymupdf4llm_backend import PyMuPDF4LLMBackend

        return PyMuPDF4LLMBackend()
    if name == "docling":
        from .docling_backend import DoclingBackend

        return DoclingBackend()
    raise PdfConversionError(
        f"未対応の PDF バックエンド: {name}（対応: pymupdf4llm, docling）"
    )


@dataclass
class PdfOutcome:
    """1 ファイルの変換結果サマリ。"""

    input_path: Path
    ok: bool
    output: Path | None = None
    error: str | None = None


def convert_pdf(
    input_path: Path,
    backend: PdfBackend,
    output_dir: Path | None,
    *,
    overwrite: bool = False,
) -> PdfOutcome:
    """単一 PDF を Markdown に変換して出力する。

    例外は送出せず PdfOutcome に集約する（バッチ継続のため）。
    """
    try:
        logger.info("変換開始: %s", input_path.name)
        markdown = backend.convert(input_path)
        out = write_markdown(markdown, input_path, output_dir, overwrite=overwrite)
        logger.info("変換完了: %s (%d 文字)", input_path.name, len(markdown))
        return PdfOutcome(input_path=input_path, ok=True, output=out)
    except Exception as exc:  # noqa: BLE001 - ファイル単位で握り、バッチ継続
        logger.error("失敗: %s: %s", input_path.name, exc)
        return PdfOutcome(input_path=input_path, ok=False, output=None, error=str(exc))
