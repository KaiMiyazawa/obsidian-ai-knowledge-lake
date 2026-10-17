"""ffmpeg による焼き込みプレビュー生成。

字幕（ASS）を動画へ焼き込んだ確認用 mp4 を作る。見た目・タイミング・改行を
編集前に一括確認するのが目的（`--preview`）。動画入力のみ対象。
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from ..errors import TranscripterError
from ..logging_conf import get_logger
from ..output.ass import render_ass
from .audio import VIDEO_EXTS, check_ffmpeg
from .subtitle.model import Cue
from .subtitle.style import SubtitleStyle

logger = get_logger()


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def _escape_filter_path(path: Path) -> str:
    """ffmpeg フィルタ引数用にパスをエスケープする（\\ : ' を処理）。"""
    s = str(path)
    s = s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return s


def build_preview(
    input_video: Path,
    cues: list[Cue],
    out_path: Path,
    *,
    style: SubtitleStyle | None = None,
    height: int | None = 1080,
    fps: int | None = 30,
    ffmpeg: str = "ffmpeg",
    overwrite: bool = False,
) -> Path:
    """動画に字幕を焼き込んだプレビュー mp4 を生成して out_path を返す。

    height/fps を指定すると、確認用に**アップスケールせず**上限までダウンスケール
    （4K/高fps 素材の焼き込みが重すぎないように）。None で元の解像度/fps を保持。
    最終的な高品質仕上げは DaVinci 側で行う前提の「確認用」出力。
    """
    if not is_video(input_video):
        raise TranscripterError(
            f"プレビューは動画入力のみ対応です（音声ファイルは非対応）: {input_video.name}"
        )
    if out_path.exists() and not overwrite:
        logger.warning("既存のためスキップ: %s（--overwrite で上書き）", out_path)
        return out_path

    ffmpeg_bin = check_ffmpeg(ffmpeg)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        ass_path = Path(td) / "sub.ass"
        ass_path.write_text(render_ass(cues, style or SubtitleStyle()), encoding="utf-8")
        # スケール → fps → 字幕焼き込み の順（1080相当のフレームに ASS を合わせる）
        chain: list[str] = []
        if height and height > 0:
            chain.append(f"scale=-2:'min(ih,{height})'")
        if fps and fps > 0:
            chain.append(f"fps={fps}")
        chain.append(f"ass={_escape_filter_path(ass_path)}")
        vf = ",".join(chain)
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(input_video),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(out_path),
        ]
        logger.debug("FFmpeg(preview): %s", " ".join(cmd))
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        except OSError as exc:  # pragma: no cover
            raise TranscripterError(f"FFmpeg の起動に失敗しました: {exc}") from exc

    if result.returncode != 0 or not out_path.exists():
        stderr = (result.stderr or "").strip()
        raise TranscripterError(
            f"プレビュー生成に失敗しました: {input_video.name}\n  FFmpeg: {stderr or '不明なエラー'}"
        )
    logger.info("プレビュー出力: %s", out_path)
    return out_path
