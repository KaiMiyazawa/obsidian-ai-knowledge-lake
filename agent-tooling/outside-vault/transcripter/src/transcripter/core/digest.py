"""動画ダイジェスト: 「AI が動画の中身を把握する」ための時刻付き台帳を作る。

動画 → （文字起こし JSON）＋（一定間隔の静止画）＋（コンタクトシート）→ ``digest.md``。
すべてローカルで完結する（外部送信なし）。Claude Code など AI が ``digest.md`` を読み、
必要な区間のコンタクトシート/静止画だけを画像として開く使い方を想定している。

静止画の抽出は ``-ss`` で位置を飛ばす方式（4K/120fps の素材で ``fps`` フィルタが全フレームを
復号して遅いのを避ける）。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Segment:
    """文字起こしの1区間（JSON の segment と同じ最小限のフィールド）。"""

    start: float
    end: float
    text: str


@dataclass
class DigestOptions:
    interval_s: float = 10.0  # 静止画・章の間隔（秒）
    frame_width: int = 640  # 静止画の幅（px）
    sheet_cols: int = 4  # コンタクトシートの列数
    sheet_rows: int = 4  # コンタクトシートの行数（1枚あたり cols*rows コマ）
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- 純粋関数（テスト対象）


def frame_times(duration: float, interval: float) -> list[float]:
    """0 秒から ``interval`` 秒おきの抽出時刻。末尾ちょうどは除外（最終フレームが取れない）。"""
    if duration <= 0 or interval <= 0:
        return []
    times: list[float] = []
    t = 0.0
    while t < duration - 0.05:
        times.append(round(t, 3))
        t += interval
    return times


def load_segments(json_path: Path) -> list[Segment]:
    """``transcripter transcribe --format json`` の出力を読む。"""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    return [
        Segment(float(s["start"]), float(s["end"]), str(s["text"]).strip())
        for s in data.get("segments", [])
        if str(s.get("text", "")).strip()
    ]


def segments_in_window(segments: list[Segment], start: float, end: float) -> list[Segment]:
    """``[start, end)`` に開始時刻が入る区間（開始時刻ベースで一意に章へ割り当てる）。"""
    return [s for s in segments if start <= s.start < end]


def _short(seconds: float) -> str:
    """``MM:SS``（1時間以上は ``H:MM:SS``）。ミリ秒は出さない。"""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def render_markdown(
    *,
    video: Path,
    duration: float,
    width: int,
    height: int,
    times: list[float],
    frame_files: list[str],
    sheets: list[tuple[str, float, float]],
    segments: list[Segment] | None,
    interval: float,
) -> str:
    """AI が読む ``digest.md`` を組み立てる。

    ``frame_files`` は ``times`` と同じ順の相対パス。``sheets`` は
    ``(相対パス, 先頭時刻, 末尾時刻)``。
    """
    lines: list[str] = []
    lines.append(f"# 動画ダイジェスト: {video.name}")
    lines.append("")
    lines.append(f"- 長さ: {_short(duration)}（{duration:.1f} 秒）／解像度: {width}x{height}")
    lines.append(f"- 静止画の間隔: {interval:g} 秒（{len(times)} コマ）")
    lines.append(f"- 文字起こし: {'あり' if segments is not None else 'なし（--no-transcribe）'}")
    lines.append("- 使い方: 下の章ごとに、画像は相対パスで開ける。全体像はコンタクトシートから。")
    lines.append("")

    if sheets:
        lines.append("## コンタクトシート（全体像）")
        lines.append("")
        for rel, t0, t1 in sheets:
            lines.append(f"- `{rel}`: {_short(t0)} 〜 {_short(t1)}")
        lines.append("")

    lines.append("## 章ごとの内容")
    lines.append("")
    for i, t in enumerate(times):
        t_end = times[i + 1] if i + 1 < len(times) else duration
        lines.append(f"### {_short(t)} 〜 {_short(t_end)}")
        lines.append("")
        lines.append(f"- 静止画: `{frame_files[i]}`（{_short(t)} 時点）")
        if segments is not None:
            texts = [s.text for s in segments_in_window(segments, t, t_end)]
            if texts:
                lines.append("- 発話:")
                for s in segments_in_window(segments, t, t_end):
                    lines.append(f"  - [{_short(s.start)}] {s.text}")
            else:
                lines.append("- 発話: （なし）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------- ffmpeg / ffprobe（実行系）


def probe(video: Path, opts: DigestOptions) -> tuple[float, int, int]:
    """(長さ秒, 幅, 高さ)。映像ストリームが無ければ ValueError。"""
    out = subprocess.run(
        [
            opts.ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-show_entries", "format=duration",
            "-of", "json", str(video),
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    streams = data.get("streams") or []
    if not streams:
        raise ValueError(f"映像ストリームがありません: {video}")
    return (
        float(data["format"]["duration"]),
        int(streams[0]["width"]),
        int(streams[0]["height"]),
    )


def extract_frames(
    video: Path, times: list[float], out_dir: Path, opts: DigestOptions
) -> list[Path]:
    """各時刻の静止画を書き出す（位置指定で1枚ずつ。既にあれば再利用）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for t in times:
        f = out_dir / f"f_{int(round(t)):05d}.jpg"
        if not f.exists():
            subprocess.run(
                [
                    opts.ffmpeg, "-v", "error", "-y", "-ss", f"{t}", "-i", str(video),
                    "-frames:v", "1", "-vf", f"scale={opts.frame_width}:-2", "-q:v", "4",
                    str(f),
                ],
                check=True, capture_output=True,
            )
        files.append(f)
    return files


def make_sheets(
    frames: list[Path], times: list[float], out_dir: Path, opts: DigestOptions
) -> list[tuple[Path, float, float]]:
    """静止画を ``cols x rows`` ごとにタイル状の1枚へまとめる（AI が1回で全体を見られる）。"""
    per = opts.sheet_cols * opts.sheet_rows
    sheets: list[tuple[Path, float, float]] = []
    for n, start in enumerate(range(0, len(frames), per)):
        chunk = frames[start : start + per]
        if not chunk:
            continue
        cols = min(opts.sheet_cols, len(chunk))
        rows = -(-len(chunk) // cols)  # 切り上げ（余白の黒い行を作らない）
        sheet = out_dir / f"sheet_{n + 1:02d}.jpg"
        list_file = out_dir / f".sheet_{n + 1:02d}.txt"
        list_file.write_text(
            "".join(f"file '{p.resolve()}'\nduration 1\n" for p in chunk), encoding="utf-8"
        )
        subprocess.run(
            [
                opts.ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_file), "-vf",
                f"tile={cols}x{rows}:padding=4:margin=4",
                "-frames:v", "1", "-q:v", "4", str(sheet),
            ],
            check=True, capture_output=True,
        )
        list_file.unlink(missing_ok=True)
        sheets.append((sheet, times[start], times[start + len(chunk) - 1]))
    return sheets


def build_digest(
    video: Path,
    out_dir: Path,
    opts: DigestOptions,
    segments: list[Segment] | None,
) -> Path:
    """ダイジェスト一式を ``out_dir`` に作り、``digest.md`` のパスを返す。"""
    video = Path(video)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    duration, width, height = probe(video, opts)
    times = frame_times(duration, opts.interval_s)
    if not times:
        raise ValueError("動画の長さが取得できませんでした。")
    frames = extract_frames(video, times, out_dir / "frames", opts)
    sheets = make_sheets(frames, times, out_dir, opts)

    md = render_markdown(
        video=video,
        duration=duration,
        width=width,
        height=height,
        times=times,
        frame_files=[str(f.relative_to(out_dir)) for f in frames],
        sheets=[(str(p.relative_to(out_dir)), t0, t1) for p, t0, t1 in sheets],
        segments=segments,
        interval=opts.interval_s,
    )
    md_path = out_dir / "digest.md"
    md_path.write_text(md, encoding="utf-8")
    return md_path
