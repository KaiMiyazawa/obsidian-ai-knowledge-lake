"""ツール固有の例外と終了コード。

終了コード方針（SPEC §19）:
    0 = 全成功
    1 = 一部ファイル失敗
    2 = 前提条件エラー（FFmpeg 未導入・入力なし・出力先不可 など）
"""

from __future__ import annotations


class TranscripterError(Exception):
    """transcripter のベース例外。"""


class PreconditionError(TranscripterError):
    """前提条件が満たされていない（終了コード 2）。

    例: FFmpeg 未導入、入力が存在しない、出力先に書き込めない。
    対処方法をメッセージに含めること。
    """


class AudioExtractionError(TranscripterError):
    """FFmpeg による音声抽出に失敗（個別ファイルエラー）。"""


class TranscriptionError(TranscripterError):
    """文字起こし処理中のエラー（個別ファイルエラー）。"""


class PdfConversionError(TranscripterError):
    """PDF → Markdown 変換中のエラー（個別ファイルエラー）。"""


# 終了コード
EXIT_OK = 0
EXIT_PARTIAL_FAILURE = 1
EXIT_PRECONDITION = 2
