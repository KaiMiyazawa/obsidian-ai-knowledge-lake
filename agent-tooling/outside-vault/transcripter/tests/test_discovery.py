from transcripter.discovery import collect_inputs


def test_single_supported_file(tmp_path):
    f = tmp_path / "a.mp3"
    f.touch()
    assert collect_inputs([f]) == [f.resolve()]


def test_unsupported_file_skipped(tmp_path):
    f = tmp_path / "a.txt"
    f.touch()
    assert collect_inputs([f]) == []


def test_directory_non_recursive(tmp_path):
    (tmp_path / "a.mp3").touch()
    (tmp_path / "b.wav").touch()
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.mp4").touch()
    result = collect_inputs([tmp_path], recursive=False)
    names = sorted(p.name for p in result)
    assert names == ["a.mp3", "b.wav"]


def test_directory_recursive(tmp_path):
    (tmp_path / "a.mp3").touch()
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.mp4").touch()
    result = collect_inputs([tmp_path], recursive=True)
    names = sorted(p.name for p in result)
    assert names == ["a.mp3", "c.mp4"]


def test_nonexistent_skipped(tmp_path):
    assert collect_inputs([tmp_path / "nope.mp3"]) == []


def test_dedup(tmp_path):
    f = tmp_path / "a.mp3"
    f.touch()
    assert collect_inputs([f, f]) == [f.resolve()]
