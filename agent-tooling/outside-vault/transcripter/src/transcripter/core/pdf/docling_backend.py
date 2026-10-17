"""docling バックエンド（任意・高精度）。

スキャン画像 PDF や複雑な表で pymupdf4llm が崩れる場合の保険。
別途インストールが必要: `uv sync --extra docling`（重い・モデルDLあり）。

注意: デジタル PDF では OCR を切る（do_ocr=False）ことでテキスト層を使い、
日本語が 1 文字ずつ分割される問題を避ける。スキャン PDF は ocr=True を指定する。
"""

from __future__ import annotations

from pathlib import Path

from ...errors import PdfConversionError
from ...logging_conf import get_logger

logger = get_logger()


class DoclingBackend:
    """docling による PdfBackend 実装。"""

    name = "docling"

    def __init__(self, ocr: bool = False) -> None:
        self.ocr = ocr
        self._converter = None  # 遅延生成

    def _ensure_converter(self):
        if self._converter is not None:
            return self._converter
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:  # pragma: no cover
            raise PdfConversionError(
                "docling がインストールされていません。"
                "`uv sync --extra docling`（または pip install docling）が必要です。"
            ) from exc

        opts = PdfPipelineOptions()
        opts.do_ocr = self.ocr  # デジタルPDFは False（テキスト層を使う）
        self._converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
        return self._converter

    def convert(self, pdf_path: Path) -> str:
        converter = self._ensure_converter()
        logger.debug("docling で変換: %s (ocr=%s)", pdf_path, self.ocr)
        try:
            result = converter.convert(str(pdf_path))
            return result.document.export_to_markdown()
        except Exception as exc:  # noqa: BLE001
            raise PdfConversionError(
                f"PDF 変換に失敗しました: {pdf_path.name}: {exc}"
            ) from exc
