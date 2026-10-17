"""LLM 後補正モジュールのテスト（実際のLLMは呼ばず、パースと結線を検証）。"""

from __future__ import annotations

import pytest

from transcripter.config import Config
from transcripter.core.correct import correct_texts, make_corrector
from transcripter.core.correct.prompt import (
    build_user_prompt,
    parse_response,
)
from transcripter.core.transcriber import _build_initial_prompt


class FakeCorrector:
    """入力の「引き地」を「引地」に直すだけの疑似バックエンド。"""

    name = "fake"

    def __init__(self, fail: bool = False, wrong_len: bool = False) -> None:
        self.fail = fail
        self.wrong_len = wrong_len
        self.calls = 0

    def correct_batch(self, texts, glossary):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        if self.wrong_len:
            return texts[:-1]  # 件数不一致
        return [t.replace("引き地", "引地") for t in texts]


# --- parse_response ---------------------------------------------------------- #

def test_parse_response_valid():
    out = parse_response('{"lines": ["あ", "い"]}', 2)
    assert out == ["あ", "い"]


def test_parse_response_fenced_and_surrounded():
    raw = 'ここが結果です:\n```json\n{"lines": ["x"]}\n```'
    assert parse_response(raw, 1) == ["x"]


def test_parse_response_length_mismatch_returns_none():
    assert parse_response('{"lines": ["a"]}', 2) is None


def test_parse_response_garbage_returns_none():
    assert parse_response("not json at all", 1) is None


# --- correct_texts ----------------------------------------------------------- #

def test_correct_texts_happy():
    fc = FakeCorrector()
    out = correct_texts(fc, ["引き地さん", "こんにちは"])
    assert out == ["引地さん", "こんにちは"]


def test_correct_texts_failure_keeps_original():
    fc = FakeCorrector(fail=True)
    src = ["引き地さん"]
    assert correct_texts(fc, src) == src  # 例外でも原文維持


def test_correct_texts_length_mismatch_keeps_original():
    fc = FakeCorrector(wrong_len=True)
    src = ["引き地A", "引き地B"]
    assert correct_texts(fc, src) == src


def test_correct_texts_blank_passthrough_not_sent():
    fc = FakeCorrector()
    out = correct_texts(fc, ["  ", "引き地"])
    assert out == ["  ", "引地"]


# --- make_corrector ---------------------------------------------------------- #

def test_make_corrector_disabled_returns_none():
    assert make_corrector(Config()) is None


def test_make_corrector_ollama():
    cfg = Config(llm_correct=True, llm_backend="ollama")
    c = make_corrector(cfg)
    assert c is not None and c.name == "ollama"


def test_make_corrector_anthropic_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = Config(llm_correct=True, llm_backend="anthropic", llm_api_key="")
    with pytest.raises(Exception):
        make_corrector(cfg)


def test_invalid_llm_backend_rejected():
    cfg = Config(llm_backend="bogus")
    with pytest.raises(ValueError):
        cfg.validate()


# --- prompt / initial_prompt ------------------------------------------------- #

def test_build_user_prompt_includes_glossary():
    p = build_user_prompt(["x"], [("引き地", "引地")])
    assert "引き地" in p and "引地" in p


def test_initial_prompt_from_vocab():
    cfg = Config(vocab=["神戸", "ハーバーランド"])
    p = _build_initial_prompt(cfg)
    assert p and "神戸" in p and "ハーバーランド" in p


def test_initial_prompt_explicit_wins():
    cfg = Config(vocab=["神戸"], initial_prompt="直接指定")
    assert _build_initial_prompt(cfg) == "直接指定"


def test_initial_prompt_none_when_empty():
    assert _build_initial_prompt(Config()) is None
