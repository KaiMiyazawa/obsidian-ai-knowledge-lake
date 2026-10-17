"""タイムコード整形。

Phase 1 の時刻つき txt と、将来の SRT/VTT（todo.md）で共用する。
SRT はミリ秒区切りが ","、VTT は "." である点に注意。
"""

from __future__ import annotations


def format_timestamp(seconds: float, *, sep: str = ".", with_ms: bool = True) -> str:
    """秒(float) を HH:MM:SS[sepMMM] に整形する。

    Args:
        seconds: 秒。負値は 0 に丸める。
        sep: ミリ秒の区切り文字（SRT="," / VTT="."）。
        with_ms: ミリ秒を含めるか（時刻つき txt では False で HH:MM:SS）。
    """
    if seconds is None or seconds < 0 or seconds != seconds:  # None/負/NaN ガード
        seconds = 0.0
    ms_total = round(seconds * 1000)
    hours, ms_total = divmod(ms_total, 3_600_000)
    minutes, ms_total = divmod(ms_total, 60_000)
    secs, ms = divmod(ms_total, 1000)
    if with_ms:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_timestamp_ass(seconds: float) -> str:
    """秒(float) を ASS の H:MM:SS.cc（1/100 秒・時は 1 桁）へ整形する。"""
    if seconds is None or seconds < 0 or seconds != seconds:  # None/負/NaN ガード
        seconds = 0.0
    cs_total = round(seconds * 100)
    hours, cs_total = divmod(cs_total, 360_000)
    minutes, cs_total = divmod(cs_total, 6_000)
    secs, cs = divmod(cs_total, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"
