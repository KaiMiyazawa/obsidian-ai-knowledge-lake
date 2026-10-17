"""digest（動画ダイジェスト）の純粋関数テスト。ffmpeg は使わない。"""

from pathlib import Path

from transcripter.core.digest import (
    Segment,
    frame_times,
    load_segments,
    render_markdown,
    segments_in_window,
)


def test_frame_times_basic():
    assert frame_times(25, 10) == [0.0, 10.0, 20.0]


def test_frame_times_excludes_exact_end():
    assert frame_times(20, 10) == [0.0, 10.0]


def test_frame_times_invalid():
    assert frame_times(0, 10) == []
    assert frame_times(10, 0) == []


def test_segments_in_window_uses_start_time():
    segs = [Segment(0, 3, "a"), Segment(9.9, 12, "b"), Segment(10.0, 11, "c")]
    assert [s.text for s in segments_in_window(segs, 0, 10)] == ["a", "b"]
    assert [s.text for s in segments_in_window(segs, 10, 20)] == ["c"]


def test_load_segments_skips_blank(tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text(
        '{"segments": [{"start": 1, "end": 2, "text": " こんにちは "},'
        ' {"start": 3, "end": 4, "text": "  "}]}',
        encoding="utf-8",
    )
    segs = load_segments(p)
    assert len(segs) == 1 and segs[0].text == "こんにちは"


def _md(segments):
    return render_markdown(
        video=Path("trip.mp4"),
        duration=65.0,
        width=1920,
        height=1080,
        times=[0.0, 30.0, 60.0],
        frame_files=["frames/f_00000.jpg", "frames/f_00030.jpg", "frames/f_00060.jpg"],
        sheets=[("sheet_01.jpg", 0.0, 60.0)],
        segments=segments,
        interval=30,
    )


def test_render_markdown_with_transcript():
    md = _md([Segment(5, 8, "ここがハーバーランド"), Segment(62, 64, "でけー")])
    assert "# 動画ダイジェスト: trip.mp4" in md
    assert "01:05" in md  # 長さ
    assert "`sheet_01.jpg`" in md
    assert "[00:05] ここがハーバーランド" in md
    assert "[01:02] でけー" in md
    assert "発話: （なし）" in md  # 30〜60秒は発話なし


def test_render_markdown_without_transcript():
    md = _md(None)
    assert "なし（--no-transcribe）" in md
    assert "発話" not in md
