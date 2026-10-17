"""rich ベースのロギング設定。

コンソールは整形表示、--log-file 指定時は同内容をプレーンテキストで保存する。
"""

from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler

LOGGER_NAME = "transcripter"

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def setup_logging(level: str = "info", log_file: str | None = None) -> logging.Logger:
    """ロガーを構成して返す。

    Args:
        level: debug / info / warning / error
        log_file: 指定があれば同内容をファイルにも出力。
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_LEVELS.get(level.lower(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    # コンソール（rich）。時刻はバーと干渉しないよう簡潔に。
    console_handler = RichHandler(
        rich_tracebacks=(level.lower() == "debug"),
        show_path=False,
        show_time=False,
        markup=False,
    )
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """構成済みロガーを取得（未構成なら既定 info で構成）。"""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        return setup_logging()
    return logger
