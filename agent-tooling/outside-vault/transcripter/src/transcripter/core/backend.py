"""推論バックエンドの抽象インターフェースとデータ型。

将来 whisper.cpp / openai-whisper へ差し替え可能にするための境界。
CLI / output 層はこの型にのみ依存する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol


@dataclass
class Word:
    """単語（トークン）単位の時刻。

    faster-whisper の `word_timestamps=True` 時に取得できる。
    字幕整形（reflow）で自然な区切り・改行位置を決めるのに使う。
    text は元のスペースを保持する（英語の語間再構成のため）。
    speaker は話者分離（WhisperX/pyannote）時のみ埋まる。
    """

    start: float
    end: float
    text: str
    speaker: str | None = None


@dataclass
class Segment:
    """文字起こしの 1 区間。

    start / end は秒（float）。txt では未使用だが、json 出力と字幕で使う。
    words は word_timestamps 有効時のみ埋まる（無効なら空）。
    """

    id: int
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None


@dataclass
class TranscriptionResult:
    """1 ファイル分の結果。"""

    language: str
    duration: float
    segments: list[Segment] = field(default_factory=list)

    @property
    def text(self) -> str:
        """全 segment を連結した本文（時刻なし）。"""
        return "".join(s.text for s in self.segments).strip()


class Backend(Protocol):
    """推論バックェンドのインターフェース。"""

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
        """音声を文字起こしする。

        Args:
            initial_prompt: 固有名詞・専門用語のヒント（認識を語彙側へバイアス）。
            condition_on_previous_text: False で直前テキストに条件付けせず、
                日本語のループ幻覚・引きずりを抑える。

        Returns:
            (segments_iterator, language, duration_seconds)
            segments は遅延評価のイテレータ（長時間ファイルのストリーム処理用）。
        """
        ...
