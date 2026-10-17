"""WebVTT ライタ。

先頭に `WEBVTT` + 空行。ミリ秒区切りは "."。インデックスは省略。
"""

from __future__ import annotations

from pathlib import Path

from ..core.subtitle.model import Cue
from .srt import cue_text
from .timefmt import format_timestamp


def render_vtt(cues: list[Cue], *, speaker_labels: bool = False) -> str:
    """Cue 列 → VTT 文字列。"""
    blocks: list[str] = ["WEBVTT\n"]
    for cue in cues:
        start = format_timestamp(cue.start, sep=".")
        end = format_timestamp(cue.end, sep=".")
        blocks.append(f"{start} --> {end}\n{cue_text(cue, speaker_labels)}\n")
    return "\n".join(blocks)


def write_vtt(cues: list[Cue], out_path: Path, *, speaker_labels: bool = False) -> None:
    out_path.write_text(render_vtt(cues, speaker_labels=speaker_labels), encoding="utf-8")
