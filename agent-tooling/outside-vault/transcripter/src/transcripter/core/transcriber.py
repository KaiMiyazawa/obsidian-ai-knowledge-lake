"""文字起こしオーケストレーション。

1 ファイルを: 音声抽出 → 推論(stream) → 進捗更新 → 出力 の順に処理する。
長時間ファイルに備え segment はストリームで受け取り、メモリ常駐を避ける。
失敗しても呼び出し側でファイル単位に継続できるよう、例外は個別に投げる。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..logging_conf import get_logger
from ..output.writer import SUBTITLE_FORMATS, write_outputs
from ..progress import file_progress
from .audio import cleanup_temp, extract_audio
from .backend import Backend, TranscriptionResult
from .burnin import build_preview, is_video
from .correct import correct_texts, make_corrector
from .faster_whisper_backend import FasterWhisperBackend
from .subtitle.reflow import build_cues, wrap_text


def make_backend(config: Config) -> Backend:
    """設定に応じて推論バックエンドを生成する（1 回ロードして再利用）。"""
    if config.asr_backend == "whisperx":
        from .whisperx_backend import WhisperXBackend

        return WhisperXBackend(
            model=config.model,
            device=config.device,
            compute_type=config.compute_type,
            diarize=config.diarize,
            hf_token=config.hf_token,
        )
    return FasterWhisperBackend(
        model=config.model,
        device=config.device,
        compute_type=config.compute_type,
        cpu_threads=config.cpu_threads,
        model_cache=config.model_cache,
    )

logger = get_logger()


def _build_initial_prompt(config: Config) -> str | None:
    """語彙ヒント（固有名詞）から initial_prompt を組み立てる。"""
    if config.initial_prompt:
        return config.initial_prompt
    if config.vocab:
        return "以下の固有名詞・用語が登場します: " + "、".join(config.vocab) + "。"
    return None


@dataclass
class FileOutcome:
    """1 ファイルの処理結果サマリ。"""

    input_path: Path
    ok: bool
    outputs: list[Path]
    error: str | None = None


def transcribe_file(
    input_path: Path,
    backend: Backend,
    config: Config,
    *,
    vad: bool = False,
    overwrite: bool = False,
    show_progress: bool = True,
) -> FileOutcome:
    """単一ファイルを文字起こしして出力する。

    例外は送出せず FileOutcome に集約する（バッチ継続のため）。
    """
    temp_wav: Path | None = None
    try:
        logger.info("処理開始: %s", input_path.name)

        # 1) 音声抽出（動画/音声を 16kHz mono wav に正規化。任意でノイズ低減）
        temp_wav, is_temp = extract_audio(
            input_path, ffmpeg=config.ffmpeg, denoise=config.denoise
        )

        # 2) 推論（ストリーム）
        # 字幕系フォーマット（srt/vtt/ass）要求時は word 単位時刻を自動有効化。
        need_words = config.word_timestamps or any(
            f in SUBTITLE_FORMATS for f in config.formats
        )
        seg_iter, language, duration = backend.transcribe_stream(
            temp_wav,
            language=config.language,
            beam_size=config.beam_size,
            vad_filter=vad,
            word_timestamps=need_words,
            initial_prompt=_build_initial_prompt(config),
            condition_on_previous_text=config.condition_on_previous_text,
        )

        # 3) segment 収集 + 進捗
        result = TranscriptionResult(language=language, duration=duration)
        if show_progress:
            with file_progress(input_path.name, duration) as bar:
                for seg in seg_iter:
                    result.segments.append(seg)
                    bar.advance_to(seg.end)
                bar.finish()
        else:
            for seg in seg_iter:
                result.segments.append(seg)

        logger.info(
            "認識完了: %s (言語=%s, 尺=%.1fs, segment数=%d)",
            input_path.name, language, duration, len(result.segments),
        )

        # 4) LLM 後補正（任意）＋ 字幕 Cue の事前生成（出力とプレビューで共有）
        corrector = make_corrector(config)
        glossary = list(config.subtitle.term_map)
        need_subs = any(f in SUBTITLE_FORMATS for f in config.formats)
        want_preview = config.preview and is_video(input_path)

        cues = None
        if need_subs or want_preview:
            cues = build_cues(result.segments, config.subtitle)
            if corrector is not None and cues:
                logger.info("LLM後補正（字幕）: backend=%s", corrector.name)
                fixed = correct_texts(
                    corrector, [c.text for c in cues], glossary
                )
                for cue, new_text in zip(cues, fixed):
                    if new_text and new_text != cue.text:
                        cue.lines = wrap_text(new_text, config.subtitle)

        # txt/json 用に segment 本文も補正（要求時のみ）
        if corrector is not None and any(f in ("txt", "json") for f in config.formats):
            logger.info("LLM後補正（本文）: backend=%s", corrector.name)
            seg_fixed = correct_texts(
                corrector, [s.text for s in result.segments], glossary
            )
            for seg, new_text in zip(result.segments, seg_fixed):
                if new_text:
                    seg.text = new_text

        # 5) 出力
        out_dir = Path(config.output_dir).expanduser() if config.output_dir else None
        outputs = write_outputs(
            result,
            input_path,
            config.formats,
            out_dir,
            timestamps=config.timestamps,
            overwrite=overwrite,
            subtitle=config.subtitle,
            style=config.subtitle_style,
            cues=cues,
        )

        # 6) 焼き込みプレビュー（動画入力かつ --preview 時のみ。失敗しても本処理は成功扱い）
        if want_preview:
            base_dir = out_dir or input_path.parent
            preview_path = base_dir / f"{input_path.stem}_preview.mp4"
            try:
                if cues is None:
                    cues = build_cues(result.segments, config.subtitle)
                build_preview(
                    input_path,
                    cues,
                    preview_path,
                    style=config.subtitle_style,
                    height=config.preview_height or None,
                    fps=config.preview_fps or None,
                    ffmpeg=config.ffmpeg,
                    overwrite=overwrite,
                )
                outputs.append(preview_path)
            except Exception as exc:  # noqa: BLE001 - プレビュー失敗は致命的でない
                logger.warning("プレビュー生成をスキップ: %s: %s", input_path.name, exc)
        elif config.preview and not is_video(input_path):
            logger.info("プレビューは動画入力のみ対応のためスキップ: %s", input_path.name)

        return FileOutcome(input_path=input_path, ok=True, outputs=outputs)

    except Exception as exc:  # noqa: BLE001 - ファイル単位で握り、バッチ継続
        logger.error("失敗: %s: %s", input_path.name, exc)
        return FileOutcome(input_path=input_path, ok=False, outputs=[], error=str(exc))
    finally:
        if temp_wav is not None:
            cleanup_temp(temp_wav)
