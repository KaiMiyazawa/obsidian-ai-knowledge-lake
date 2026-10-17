"""ASS（Advanced SubStation Alpha）ライタ。

フォント・色・縁取り・帯・位置などのスタイルを 1 つの Default スタイルに写す。
焼き込み（ffmpeg `ass=...`）や対応プレイヤー向け。
※ DaVinci Resolve は ASS の装飾をほぼ無視するため、Resolve では SRT を使い
　インスペクタでトラックに適用する（docs/davinci-workflow.md）。
"""

from __future__ import annotations

from pathlib import Path

from ..core.subtitle.model import Cue
from ..core.subtitle.postprocess import humanize_speaker
from ..core.subtitle.style import (
    PLAY_RES_X,
    PLAY_RES_Y,
    SubtitleStyle,
    ass_color,
)
from .timefmt import format_timestamp_ass

_MARGIN_H = 40  # 左右マージン（px, PlayRes 基準）

_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
    "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding"
)
_EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
)


def _style_line(style: SubtitleStyle) -> str:
    primary = ass_color(style.text_color, 100)
    outline_c = ass_color(style.outline_color, 100)
    back = ass_color(style.box_color, style.box_opacity)
    bold = -1 if style.font_bold else 0
    italic = -1 if style.font_italic else 0
    outline_w = style.outline_width if style.outline else 0
    return (
        f"Style: Default,{style.font_family},{style.font_size_px()},"
        f"{primary},{primary},{outline_c},{back},"
        f"{bold},{italic},0,0,100,100,0,0,"
        f"{style.border_style()},{outline_w:g},{style.shadow:g},"
        f"{style.ass_alignment()},{_MARGIN_H},{_MARGIN_H},{style.margin_v_px()},1"
    )


def render_ass(
    cues: list[Cue], style: SubtitleStyle | None = None, *, speaker_labels: bool = False
) -> str:
    style = style or SubtitleStyle()
    lines = [
        "[Script Info]",
        "; transcripter で生成",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {PLAY_RES_X}",
        f"PlayResY: {PLAY_RES_Y}",
        "",
        "[V4+ Styles]",
        _STYLE_FORMAT,
        _style_line(style),
        "",
        "[Events]",
        _EVENT_FORMAT,
    ]
    for cue in cues:
        start = format_timestamp_ass(cue.start)
        end = format_timestamp_ass(cue.end)
        rendered = list(cue.lines)
        if speaker_labels and cue.speaker:
            rendered[0] = f"{humanize_speaker(cue.speaker)}：{rendered[0]}"
        text = "\\N".join(rendered)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def write_ass(
    cues: list[Cue],
    out_path: Path,
    style: SubtitleStyle | None = None,
    *,
    speaker_labels: bool = False,
) -> None:
    out_path.write_text(
        render_ass(cues, style, speaker_labels=speaker_labels), encoding="utf-8"
    )
