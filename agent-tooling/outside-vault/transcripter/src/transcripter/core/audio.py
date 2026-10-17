"""FFmpeg による音声抽出・正規化。

入力（音声/動画）を Whisper 向けの 16kHz / mono / PCM16 wav に変換する。
音声ファイルでもサンプルレート等が異なることがあるため一律に正規化する。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..errors import AudioExtractionError, PreconditionError
from ..logging_conf import get_logger

logger = get_logger()

# 対応拡張子（SPEC §15）
AUDIO_EXTS = {".mp3", ".wav", ".m4a"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv"}
SUPPORTED_EXTS = AUDIO_EXTS | VIDEO_EXTS

TARGET_SAMPLE_RATE = 16000

# 屋外/アクションカメラ向けの前処理フィルタ（風切り音・ノイズ低減＋音量正規化）。
# highpass=80: 低域の風・ハンドリングノイズを削る / afftdn: FFTノイズ低減 /
# loudnorm: ラウドネス正規化（小声・音量ムラを均す）。ASR 精度向上を狙う。
DENOISE_FILTER = "highpass=f=80,afftdn=nf=-25,loudnorm=I=-16:TP=-1.5:LRA=11"


def check_ffmpeg(ffmpeg: str = "ffmpeg") -> str:
    """FFmpeg の存在を確認し、解決済みパスを返す。

    Raises:
        PreconditionError: FFmpeg が見つからない場合（導入手順つき）。
    """
    resolved = shutil.which(ffmpeg) if not Path(ffmpeg).is_absolute() else ffmpeg
    if not resolved or not Path(resolved).exists():
        raise PreconditionError(
            "FFmpeg が見つかりません。音声/動画の読み込みに必須です。\n"
            "  macOS:   brew install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  Linux:   sudo apt install ffmpeg\n"
            f"（設定 [paths].ffmpeg = \"{ffmpeg}\" を確認してください）"
        )
    return resolved


def is_supported(path: Path) -> bool:
    """対応拡張子かどうか。"""
    return path.suffix.lower() in SUPPORTED_EXTS


def extract_audio(
    input_path: Path,
    ffmpeg: str = "ffmpeg",
    workdir: Path | None = None,
    *,
    denoise: bool = False,
) -> tuple[Path, bool]:
    """入力を 16kHz/mono/wav に変換する。

    Args:
        denoise: True で風切り音・ノイズ低減＋音量正規化（屋外/アクションカメラ向け）。

    Returns:
        (wav_path, is_temp): is_temp=True なら呼び出し側が後始末（削除）する一時ファイル。

    Raises:
        AudioExtractionError: 変換に失敗（破損・音声トラックなし等）。
    """
    ffmpeg_bin = check_ffmpeg(ffmpeg)

    tmp_dir = workdir or Path(tempfile.gettempdir())
    tmp_dir.mkdir(parents=True, exist_ok=True)
    # 入力名を残しつつ衝突しにくい一時ファイル名にする
    fd_path = tmp_dir / f"{input_path.stem}.{abs(hash(str(input_path))) % 100000}.tmp.wav"

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(input_path),
        "-vn",                      # 映像を無視
        "-ac", "1",                 # モノラル
        "-ar", str(TARGET_SAMPLE_RATE),
    ]
    if denoise:
        cmd += ["-af", DENOISE_FILTER]
    cmd += [
        "-c:a", "pcm_s16le",
        str(fd_path),
    ]
    logger.debug("FFmpeg: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:  # pragma: no cover - 実行環境依存
        raise AudioExtractionError(f"FFmpeg の起動に失敗しました: {exc}") from exc

    if result.returncode != 0 or not fd_path.exists():
        stderr = (result.stderr or "").strip()
        raise AudioExtractionError(
            f"音声抽出に失敗しました: {input_path.name}\n"
            f"  FFmpeg: {stderr or '不明なエラー（音声トラックなし/破損の可能性）'}"
        )

    return fd_path, True


def cleanup_temp(path: Path) -> None:
    """一時 wav を削除（存在しなくてもエラーにしない）。"""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:  # pragma: no cover
        logger.debug("一時ファイル削除に失敗: %s (%s)", path, exc)
