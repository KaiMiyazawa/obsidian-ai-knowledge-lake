"""SRT（SubRip）ライタ。

DaVinci Resolve 取り込みの本命フォーマット（テキスト＋時刻のみ、装飾なし）。
ミリ秒区切りは "," 。連番 1 始まり、ブロック間は空行。UTF-8（BOM 任意）。
"""

from __future__ import annotations

from pathlib import Path

from ..core.subtitle.model import Cue
from ..core.subtitle.postprocess import humanize_speaker
from .timefmt import format_timestamp


def cue_text(cue: Cue, speaker_labels: bool = False) -> str:
    """字幕テキスト（必要なら話者名を前置）。"""
    if speaker_labels and cue.speaker:
        return f"{humanize_speaker(cue.speaker)}：{cue.text}"
    return cue.text


def render_srt(cues: list[Cue], *, speaker_labels: bool = False) -> str:
    """Cue 列 → SRT 文字列。"""
    blocks: list[str] = []
    for i, cue in enumerate(cues, start=1):
        start = format_timestamp(cue.start, sep=",")
        end = format_timestamp(cue.end, sep=",")
        blocks.append(f"{i}\n{start} --> {end}\n{cue_text(cue, speaker_labels)}\n")
    return "\n".join(blocks)


def write_srt(
    cues: list[Cue], out_path: Path, *, bom: bool = False, speaker_labels: bool = False
) -> None:
    content = render_srt(cues, speaker_labels=speaker_labels)
    encoding = "utf-8-sig" if bom else "utf-8"
    out_path.write_text(content, encoding=encoding)
