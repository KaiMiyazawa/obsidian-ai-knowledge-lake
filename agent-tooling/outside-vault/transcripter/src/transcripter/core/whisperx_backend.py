"""WhisperX バックエンド（任意・高精度な単語時刻＋話者分離）。

faster-whisper で文字起こし → wav2vec2 forced alignment で単語時刻を ±50ms に
高精度化 → （HFトークンがあれば）pyannote で話者分離し各単語へ話者を付与する。

重い任意依存（`uv sync --extra whisperx`）。モデルは初回DL、話者分離は
HuggingFace の gated モデル利用同意＋トークンが必要（環境変数 HF_TOKEN など）。
本モジュールは Resolve/モデル同様、実機が要るため単体テストの対象外。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ..errors import TranscriptionError
from ..logging_conf import get_logger
from .backend import Segment, Word

logger = get_logger()

# faster-whisper 名 → WhisperX(内部 faster-whisper) が解決できる名前へ寄せる
_MODEL_ALIASES = {"turbo": "large-v3-turbo"}


class WhisperXBackend:
    """WhisperX による Backend 実装（align ＋ 任意 diarize）。"""

    def __init__(
        self,
        model: str = "large-v3",
        device: str = "cpu",
        compute_type: str = "int8",
        *,
        diarize: bool = False,
        hf_token: str = "",
        batch_size: int = 8,
    ) -> None:
        self.model_name = _MODEL_ALIASES.get(model, model)
        self.device = device
        self.compute_type = compute_type
        self.diarize = diarize
        self.hf_token = hf_token
        self.batch_size = batch_size
        self._model = None
        self._diarizer = None

    def _import(self):
        try:
            import whisperx
        except ImportError as exc:  # pragma: no cover
            raise TranscriptionError(
                "whisperx がインストールされていません。"
                "`uv sync --extra whisperx` を実行してください。"
            ) from exc
        return whisperx

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
        # WhisperX は forced alignment で単語時刻を持つため word_timestamps は常に有効。
        # initial_prompt / condition_on_previous_text は内部実装差のため現状未使用。
        whisperx = self._import()
        lang = None if language in ("", "auto") else language

        try:
            if self._model is None:
                logger.info(
                    "WhisperX モデルをロード中: %s (device=%s, %s)",
                    self.model_name, self.device, self.compute_type,
                )
                self._model = whisperx.load_model(
                    self.model_name, self.device, compute_type=self.compute_type,
                    language=lang,
                )
            audio = whisperx.load_audio(str(audio_path))
            duration = len(audio) / 16000.0

            result = self._model.transcribe(audio, batch_size=self.batch_size, language=lang)
            detected = result.get("language", lang or "ja")

            # forced alignment（単語時刻の高精度化）
            align_model, metadata = whisperx.load_align_model(
                language_code=detected, device=self.device
            )
            result = whisperx.align(
                result["segments"], align_model, metadata, audio, self.device,
                return_char_alignments=False,
            )

            # 話者分離（任意）
            if self.diarize:
                result = self._apply_diarization(whisperx, audio, result)

        except TranscriptionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(
                f"WhisperX 処理に失敗しました: {audio_path.name}: {exc}"
            ) from exc

        segments = list(self._to_segments(result.get("segments", [])))

        def _iter() -> Iterator[Segment]:
            yield from segments

        return _iter(), detected, float(duration)

    def _apply_diarization(self, whisperx, audio, result):
        if not self.hf_token:
            logger.warning(
                "話者分離には HuggingFace トークンが必要です（--hf-token / HF_TOKEN）。"
                "話者ラベルなしで続行します。"
            )
            return result
        if self._diarizer is None:
            logger.info("話者分離パイプラインをロード中（pyannote）")
            self._diarizer = whisperx.DiarizationPipeline(
                use_auth_token=self.hf_token, device=self.device
            )
        diarize_segments = self._diarizer(audio)
        return whisperx.assign_word_speakers(diarize_segments, result)

    @staticmethod
    def _to_segments(raw_segments) -> Iterator[Segment]:
        for i, seg in enumerate(raw_segments):
            words: list[Word] = []
            for w in seg.get("words", []):
                if w.get("start") is None or w.get("end") is None:
                    continue
                words.append(
                    Word(
                        start=float(w["start"]),
                        end=float(w["end"]),
                        text=w.get("word", ""),
                        speaker=w.get("speaker"),
                    )
                )
            yield Segment(
                id=i,
                start=float(seg.get("start", words[0].start if words else 0.0)),
                end=float(seg.get("end", words[-1].end if words else 0.0)),
                text=seg.get("text", "".join(x.text for x in words)),
                words=words,
                speaker=seg.get("speaker"),
            )
