"""rich によるファイル単位の進捗表示。

長時間ファイルでも残り時間の目安が分かるよう、音声の総尺(duration)に対する
処理済み秒(segment.end)で進捗バーを更新する。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)


@contextmanager
def file_progress(label: str, duration: float) -> Iterator["_Updater"]:
    """1 ファイル分の進捗バーを表示するコンテキスト。

    Args:
        label: 表示名（ファイル名）。
        duration: 音声の総尺（秒）。0 以下なら不確定表示。
    """
    total = duration if duration and duration > 0 else None
    progress = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        transient=True,
    )
    with progress:
        task_id = progress.add_task(label, total=total)
        yield _Updater(progress, task_id, total)


class _Updater:
    """進捗バー更新ヘルパ。"""

    def __init__(self, progress: Progress, task_id: int, total: float | None) -> None:
        self._progress = progress
        self._task_id = task_id
        self._total = total

    def advance_to(self, processed_seconds: float) -> None:
        """処理済み秒の位置までバーを進める。"""
        if self._total:
            completed = min(processed_seconds, self._total)
            self._progress.update(self._task_id, completed=completed)

    def finish(self) -> None:
        if self._total:
            self._progress.update(self._task_id, completed=self._total)
