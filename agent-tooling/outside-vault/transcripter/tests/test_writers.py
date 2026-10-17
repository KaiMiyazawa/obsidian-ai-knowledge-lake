import json

from transcripter.core.backend import Segment, TranscriptionResult
from transcripter.output.writer import write_outputs, write_json, write_txt


def _result():
    return TranscriptionResult(
        language="ja",
        duration=6.5,
        segments=[
            Segment(id=0, start=0.0, end=3.2, text="こんにちは"),
            Segment(id=1, start=3.2, end=6.5, text="今日はいい天気ですね"),
        ],
    )


def test_txt_plain(tmp_path):
    out = tmp_path / "a.txt"
    write_txt(_result(), out)
    assert out.read_text(encoding="utf-8") == "こんにちは今日はいい天気ですね\n"


def test_txt_with_timestamps(tmp_path):
    out = tmp_path / "a.txt"
    write_txt(_result(), out, timestamps=True)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "[00:00:00] こんにちは"
    assert lines[1] == "[00:00:03] 今日はいい天気ですね"


def test_json_structure(tmp_path):
    out = tmp_path / "a.json"
    write_json(_result(), out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["language"] == "ja"
    assert data["duration"] == 6.5
    assert len(data["segments"]) == 2
    assert data["segments"][0]["start"] == 0.0
    assert data["text"] == "こんにちは今日はいい天気ですね"


def test_write_outputs_multiple_formats(tmp_path):
    written = write_outputs(
        _result(), tmp_path / "input.mp3", ["txt", "json"], tmp_path / "out",
    )
    names = sorted(p.name for p in written)
    assert names == ["input.json", "input.txt"]
    assert all(p.exists() for p in written)


def test_write_outputs_skips_existing_without_overwrite(tmp_path):
    inp = tmp_path / "input.mp3"
    (tmp_path / "input.txt").write_text("既存", encoding="utf-8")
    written = write_outputs(_result(), inp, ["txt"], tmp_path, overwrite=False)
    assert written == []  # スキップされた
    assert (tmp_path / "input.txt").read_text(encoding="utf-8") == "既存"


def test_write_outputs_overwrite(tmp_path):
    inp = tmp_path / "input.mp3"
    (tmp_path / "input.txt").write_text("既存", encoding="utf-8")
    written = write_outputs(_result(), inp, ["txt"], tmp_path, overwrite=True)
    assert len(written) == 1
    assert "既存" not in (tmp_path / "input.txt").read_text(encoding="utf-8")
