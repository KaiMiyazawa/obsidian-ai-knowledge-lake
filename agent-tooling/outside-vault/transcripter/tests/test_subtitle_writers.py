"""字幕ライタ（SRT/VTT/ASS）とスタイル変換のテスト。"""

import pytest

from transcripter.core.subtitle.model import Cue
from transcripter.core.subtitle.style import SubtitleStyle, ass_color, make_style
from transcripter.output.ass import render_ass
from transcripter.output.srt import render_srt
from transcripter.output.timefmt import format_timestamp_ass
from transcripter.output.vtt import render_vtt


def _cues():
    return [
        Cue(index=1, start=0.0, end=3.2, lines=["こんにちは"]),
        Cue(index=2, start=3.2, end=6.5, lines=["今日は", "いい天気ですね"]),
    ]


def test_srt_format():
    out = render_srt(_cues())
    blocks = out.split("\n\n")
    assert blocks[0].splitlines()[0] == "1"
    assert blocks[0].splitlines()[1] == "00:00:00,000 --> 00:00:03,200"
    assert blocks[0].splitlines()[2] == "こんにちは"
    # 2枚目は連番2、2行
    assert blocks[1].splitlines()[0] == "2"
    assert blocks[1].splitlines()[2] == "今日は"
    assert blocks[1].splitlines()[3] == "いい天気ですね"


def test_vtt_format():
    out = render_vtt(_cues())
    assert out.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:03.200" in out


def test_ass_timestamp():
    assert format_timestamp_ass(0.0) == "0:00:00.00"
    assert format_timestamp_ass(3723.45) == "1:02:03.45"


def test_ass_has_style_and_events():
    out = render_ass(_cues(), SubtitleStyle())
    assert "[V4+ Styles]" in out
    assert "Style: Default,Noto Sans JP" in out
    assert "PlayResY: 1080" in out
    # 2 行は \N で連結
    assert "今日は\\Nいい天気ですね" in out
    # Dialogue 行が cue 数だけ
    assert out.count("Dialogue:") == 2


def test_ass_color_conversion():
    # 白・不透明 → &H00FFFFFF、黒・不透明 → &H00000000
    assert ass_color("#FFFFFF", 100) == "&H00FFFFFF"
    assert ass_color("#000000", 100) == "&H00000000"
    # 不透明度 0% → アルファ FF
    assert ass_color("#000000", 0) == "&HFF000000"
    # 赤 → BGR 並びで &H000000FF
    assert ass_color("#FF0000", 100) == "&H000000FF"


def test_style_box_border():
    assert SubtitleStyle(box=False).border_style() == 1
    assert SubtitleStyle(box=True).border_style() == 3
    assert SubtitleStyle(position="bottom", alignment="center").ass_alignment() == 2
    assert SubtitleStyle(position="top", alignment="center").ass_alignment() == 8


def test_style_presets():
    assert make_style("outline").box is False
    box = make_style("box")
    assert box.box is True and box.box_opacity == 70
    # overrides が効く
    assert make_style("box", box_opacity=50).box_opacity == 50
    # 未知プリセットは ValueError
    with pytest.raises(ValueError):
        make_style("unknown")


def test_box_style_emits_border3_and_backcolour():
    out = render_ass(_cues(), make_style("box"))
    # BorderStyle=3（帯）で BackColour のアルファが不透明度70%相当（&H4C...）
    style_line = [ln for ln in out.splitlines() if ln.startswith("Style:")][0]
    fields = style_line.split(",")
    # BorderStyle は Alignment 手前、位置は固定フォーマット（後ろから数える）
    assert ",3," in style_line  # BorderStyle=3
    assert "&H4C000000" in fields  # BackColour（帯・70%）
