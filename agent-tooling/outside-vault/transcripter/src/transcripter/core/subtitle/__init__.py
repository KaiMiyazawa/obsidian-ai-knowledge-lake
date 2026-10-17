"""字幕テロップ生成: 整形（reflow）・後処理・スタイル。

Whisper の segment/word 時刻から、読みやすい字幕1枚（Cue）へ再分割し、
SRT / VTT / ASS へ書き出す。設計は docs/subtitle-telop-plan.md。
"""

from .model import Cue
from .reflow import build_cues
from .style import SubtitleStyle

__all__ = ["Cue", "build_cues", "SubtitleStyle"]
