"""話者ラベル（reflow/writer）と Web UI アプリの単体テスト。"""

import pytest

from transcripter.core.backend import Segment, Word
from transcripter.core.subtitle.postprocess import humanize_speaker
from transcripter.core.subtitle.reflow import SubtitleConfig, build_cues
from transcripter.output.srt import render_srt


def test_humanize_speaker():
    assert humanize_speaker("SPEAKER_00") == "話者1"
    assert humanize_speaker("SPEAKER_02") == "話者3"
    assert humanize_speaker("引地") == "引地"
    assert humanize_speaker(None) == ""


def test_split_on_speaker_and_majority():
    seg = Segment(
        id=0, start=0.0, end=2.0, text="",
        words=[
            Word(0.0, 0.5, "こんにちは", speaker="SPEAKER_00"),
            Word(0.55, 1.0, "ですね", speaker="SPEAKER_00"),
            Word(1.1, 1.6, "はい", speaker="SPEAKER_01"),
        ],
    )
    cfg = SubtitleConfig(split_on_speaker=True, gap_split_s=99, max_duration_s=999)
    cues = build_cues([seg], cfg)
    assert len(cues) == 2
    assert cues[0].speaker == "SPEAKER_00"
    assert cues[1].speaker == "SPEAKER_01"


def test_speaker_labels_in_srt():
    seg = Segment(
        id=0, start=0.0, end=2.0, text="",
        words=[
            Word(0.0, 0.6, "おはよう", speaker="SPEAKER_00"),
            Word(1.2, 1.8, "おはよう", speaker="SPEAKER_01"),
        ],
    )
    cfg = SubtitleConfig(split_on_speaker=True, gap_split_s=0.3, max_duration_s=999)
    cues = build_cues([seg], cfg)
    out = render_srt(cues, speaker_labels=True)
    assert "話者1：" in out
    assert "話者2：" in out
    # ラベル無効なら前置されない
    assert "話者1：" not in render_srt(cues, speaker_labels=False)


def test_no_speaker_no_split():
    # speaker が None なら話者分割は起きない
    seg = Segment(
        id=0, start=0.0, end=1.0, text="",
        words=[Word(0.0, 0.4, "あ"), Word(0.45, 0.9, "い")],
    )
    cues = build_cues([seg], SubtitleConfig(gap_split_s=99))
    assert all(c.speaker is None for c in cues)


def test_webui_app_routes(tmp_path):
    pytest.importorskip("fastapi")
    from transcripter.webui.app import create_app

    app = create_app(tmp_path)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/" in paths
    assert any(p and p.startswith("/api/transcribe") for p in paths)
