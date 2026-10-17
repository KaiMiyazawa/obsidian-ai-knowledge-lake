from transcripter.output.timefmt import format_timestamp


def test_zero():
    assert format_timestamp(0.0, sep=",") == "00:00:00,000"


def test_vtt_separator():
    assert format_timestamp(83.456, sep=".") == "00:01:23.456"


def test_srt_separator():
    assert format_timestamp(83.456, sep=",") == "00:01:23,456"


def test_over_one_hour():
    # 1h 2m 3s 500ms
    assert format_timestamp(3723.5, sep=",") == "01:02:03,500"


def test_millisecond_rounding():
    assert format_timestamp(1.2349, sep=".") == "00:00:01.235"


def test_without_ms():
    assert format_timestamp(83.9, with_ms=False) == "00:01:23"


def test_negative_and_nan_guard():
    assert format_timestamp(-5.0, sep=",") == "00:00:00,000"
    assert format_timestamp(float("nan"), sep=",") == "00:00:00,000"
