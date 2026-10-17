"""PDF → Markdown 変換のコア層。

音声側（core/）と同じ思想で、Backend を抽象化して差し替え可能にする。
既定は pymupdf4llm（軽量・ローカル・テキスト層直読）。
任意で docling（高精度/スキャン向け、別途インストール）。
"""

PDF_EXTS = {".pdf"}
