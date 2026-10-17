"""出力ライタのディスパッチ。

形式名 -> 書き出し関数。txt / json（segment）と srt / vtt / ass（字幕 Cue）。
字幕系は reflow で Cue 列を 1 度だけ生成して共用する。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.backend import TranscriptionResult
from ..core.subtitle.model import Cue
from ..core.subtitle.reflow import SubtitleConfig, build_cues
from ..core.subtitle.style import SubtitleStyle
from ..logging_conf import get_logger
from .ass import write_ass
from .srt import write_srt
from .timefmt import format_timestamp
from .vtt import write_vtt

logger = get_logger()

# 字幕（Cue ベース）の形式。
SUBTITLE_FORMATS = {"srt", "vtt", "ass"}


def write_txt(
    result: TranscriptionResult,
    out_path: Path,
    *,
    timestamps: bool = False,
) -> None:
    """プレーンテキストを書き出す。

    timestamps=False（既定）: 全 segment を連結した本文のみ。
    timestamps=True: 各 segment 先頭に [HH:MM:SS] を付与（1 行 1 segment）。
    """
    if timestamps:
        lines = [
            f"[{format_timestamp(s.start, with_ms=False)}] {s.text.strip()}"
            for s in result.segments
        ]
        content = "\n".join(lines) + ("\n" if lines else "")
    else:
        content = result.text + "\n" if result.text else ""
    out_path.write_text(content, encoding="utf-8")


def write_json(result: TranscriptionResult, out_path: Path) -> None:
    """メタ情報つき JSON を書き出す（解析・再処理用）。"""

    def _seg(s):  # noqa: ANN001 - ローカルヘルパ
        d = {
            "id": s.id,
            "start": round(s.start, 3),
            "end": round(s.end, 3),
            "text": s.text.strip(),
        }
        if s.words:
            d["words"] = [
                {"start": round(w.start, 3), "end": round(w.end, 3), "text": w.text}
                for w in s.words
            ]
        return d

    data = {
        "language": result.language,
        "duration": round(result.duration, 3),
        "segments": [_seg(s) for s in result.segments],
        "text": result.text,
    }
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# 形式 -> 拡張子
EXTENSIONS = {
    "txt": ".txt",
    "json": ".json",
    "srt": ".srt",
    "vtt": ".vtt",
    "ass": ".ass",
}


def write_outputs(
    result: TranscriptionResult,
    input_path: Path,
    formats: list[str],
    output_dir: Path | None,
    *,
    timestamps: bool = False,
    overwrite: bool = False,
    subtitle: SubtitleConfig | None = None,
    style: SubtitleStyle | None = None,
    cues: list[Cue] | None = None,
) -> list[Path]:
    """指定形式すべてを書き出し、生成パスのリストを返す。

    出力先は output_dir、無ければ入力と同じディレクトリ。
    既存ファイルは overwrite=False ならスキップ（警告）。
    字幕系（srt/vtt/ass）が含まれる場合は reflow で Cue を 1 度だけ生成する。
    cues を渡せば再生成せずそれを使う（LLM補正済み Cue の共有など）。
    """
    base_dir = output_dir or input_path.parent
    base_dir.mkdir(parents=True, exist_ok=True)

    sub_cfg = subtitle or SubtitleConfig()
    if cues is None and any(f in SUBTITLE_FORMATS for f in formats):
        cues = build_cues(result.segments, sub_cfg)
        logger.info("字幕整形: %d segment → %d 字幕(cue)", len(result.segments), len(cues))

    written: list[Path] = []
    for fmt in formats:
        ext = EXTENSIONS[fmt]
        out_path = base_dir / f"{input_path.stem}{ext}"
        if out_path.exists() and not overwrite:
            logger.warning("既存のためスキップ: %s（--overwrite で上書き）", out_path)
            continue
        if fmt == "txt":
            write_txt(result, out_path, timestamps=timestamps)
        elif fmt == "json":
            write_json(result, out_path)
        elif fmt == "srt":
            write_srt(cues or [], out_path, speaker_labels=sub_cfg.speaker_labels)
        elif fmt == "vtt":
            write_vtt(cues or [], out_path, speaker_labels=sub_cfg.speaker_labels)
        elif fmt == "ass":
            write_ass(
                cues or [], out_path, style or SubtitleStyle(),
                speaker_labels=sub_cfg.speaker_labels,
            )
        written.append(out_path)
        logger.info("出力: %s", out_path)
    return written
