"""字幕の中間データ型。

Cue = 画面に一度に出す字幕1枚（1〜2行）。start/end は秒。
lines は表示行（改行済み）。SRT/VTT/ASS ライタはこの型だけに依存する。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Cue:
    """字幕1枚。"""

    index: int
    start: float
    end: float
    lines: list[str] = field(default_factory=list)
    speaker: str | None = None

    @property
    def text(self) -> str:
        """改行区切りの表示テキスト。"""
        return "\n".join(self.lines)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)
