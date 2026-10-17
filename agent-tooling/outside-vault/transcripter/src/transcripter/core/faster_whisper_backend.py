"""faster-whisper（CTranslate2）バックエンド。

turbo モデルを既定とし、Apple Silicon では device=cpu / compute_type=int8 で動く。
モデルは初回実行時に HuggingFace Hub からダウンロードされ、
~/.cache/huggingface（または model_cache）にキャッシュされる。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from ..errors import TranscriptionError
from ..logging_conf import get_logger
from .backend import Segment, Word

logger = get_logger()


class FasterWhisperBackend:
    """faster-whisper による Backend 実装。"""

    def __init__(
        self,
        model: str = "turbo",
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        model_cache: str = "",
    ) -> None:
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.model_cache = model_cache
        self._model = None  # 遅延ロード

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        # 重い import はロード時まで遅延（CLI 起動を速く保つ）
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover
            raise TranscriptionError(
                "faster-whisper がインストールされていません。"
                "`uv sync` または `pip install faster-whisper` を実行してください。"
            ) from exc

        download_root = None
        if self.model_cache:
            cache = Path(self.model_cache).expanduser()
            cache.mkdir(parents=True, exist_ok=True)
            download_root = str(cache)
            # HuggingFace のキャッシュ先も合わせる
            os.environ.setdefault("HF_HOME", str(cache))

        logger.info(
            "モデルをロード中: %s (device=%s, compute_type=%s)",
            self.model_name, self.device, self.compute_type,
        )
        try:
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
                download_root=download_root,
            )
        except Exception as exc:  # noqa: BLE001 - ライブラリ例外を集約
            raise TranscriptionError(
                f"モデルのロードに失敗しました: {exc}\n"
                "  - 初回はモデルのダウンロードにネット接続が必要です。\n"
                "  - GPU 指定時は CUDA 12 / cuDNN 9 が必要です（Apple Silicon は device=cpu）。"
            ) from exc

    def transcribe_stream(
        self,
        audio_path: Path,
        *,
        language: str,
        beam_size: int,
        vad_filter: bool,
        word_timestamps: bool,
        initial_prompt: str | None = None,
        condition_on_previous_text: bool = True,
    ) -> tuple[Iterator[Segment], str, float]:
        self._ensure_loaded()
        assert self._model is not None

        lang = None if language in ("", "auto") else language
        try:
            raw_segments, info = self._model.transcribe(
                str(audio_path),
                language=lang,
                beam_size=beam_size,
                vad_filter=vad_filter,
                word_timestamps=word_timestamps,
                initial_prompt=initial_prompt or None,
                condition_on_previous_text=condition_on_previous_text,
            )
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(
                f"文字起こしに失敗しました: {audio_path.name}: {exc}"
            ) from exc

        def _iter() -> Iterator[Segment]:
            for seg in raw_segments:
                words: list[Word] = []
                if word_timestamps and getattr(seg, "words", None):
                    for w in seg.words:
                        # 稀に start/end が None の word があるためガード
                        if w.start is None or w.end is None:
                            continue
                        words.append(
                            Word(start=float(w.start), end=float(w.end), text=w.word)
                        )
                yield Segment(
                    id=seg.id,
                    start=float(seg.start),
                    end=float(seg.end),
                    text=seg.text,
                    words=words,
                )

        return _iter(), info.language, float(info.duration)
