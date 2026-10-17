"""補正バックエンドの抽象と共通ロジック（バッチ分割・安全なフォールバック）。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ...logging_conf import get_logger

if TYPE_CHECKING:
    from ...config import Config

logger = get_logger()

# 1 リクエストあたりの最大行数（文脈確保と応答安定のバランス）。
_BATCH = 30


class Corrector(Protocol):
    """後補正バックエンドのインターフェース。"""

    name: str

    def correct_batch(
        self, texts: list[str], glossary: list[tuple[str, str]]
    ) -> list[str] | None:
        """texts と同数の補正済み行を返す。失敗時は None（呼び出し側で原文維持）。"""
        ...


def make_corrector(config: Config) -> Corrector | None:
    """設定に応じて Corrector を生成。無効なら None。"""
    if not config.llm_correct:
        return None
    backend = config.llm_backend
    if backend == "ollama":
        from .ollama import OllamaCorrector

        return OllamaCorrector(
            model=config.llm_model or "qwen2.5:7b",
            endpoint=config.llm_endpoint or "http://localhost:11434",
        )
    if backend == "anthropic":
        from .anthropic import AnthropicCorrector

        return AnthropicCorrector(
            model=config.llm_model or "claude-haiku-4-5-20251001",
            api_key=config.llm_api_key,
        )
    raise ValueError(f"未対応の llm_backend: {backend}（対応: ollama, anthropic）")


def correct_texts(
    corrector: Corrector,
    texts: list[str],
    glossary: list[tuple[str, str]] | None = None,
) -> list[str]:
    """テキスト列をバッチ補正する。1 バッチでも失敗したらその範囲は原文を保つ。"""
    glossary = glossary or []
    out: list[str] = []
    n = len(texts)
    for i in range(0, n, _BATCH):
        chunk = texts[i : i + _BATCH]
        # 空白のみの行は送らず素通し（無駄な補正・崩れを防ぐ）
        nonblank = [t for t in chunk if t.strip()]
        if not nonblank:
            out.extend(chunk)
            continue
        try:
            fixed = corrector.correct_batch(nonblank, glossary)
        except Exception as exc:  # noqa: BLE001 - どんな失敗でも原文にフォールバック
            logger.warning("LLM補正に失敗（原文を維持）: %s", exc)
            fixed = None
        if fixed is None or len(fixed) != len(nonblank):
            out.extend(chunk)
            continue
        it = iter(fixed)
        out.extend(next(it) if t.strip() else t for t in chunk)
    return out
