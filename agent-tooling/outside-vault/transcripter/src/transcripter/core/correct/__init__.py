"""LLM による文字起こし後補正（誤変換・同音語・句読点の最小修正）。

ローカル完結を既定とする方針:
  - 既定バックエンドは **ローカル Ollama**（localhost のみと通信・外部送信なし）。
  - 外部 API（Anthropic）は **オプトイン**。有効化すると音声由来テキストが外部へ送られる。

いずれも「言い換え・要約はせず、明らかな誤りだけを直す」制約プロンプトで、
タイミング（word 時刻・cue 区間）には触れず本文テキストのみを 1 対 1 で補正する。
"""

from __future__ import annotations

from .base import Corrector, correct_texts, make_corrector

__all__ = ["Corrector", "make_corrector", "correct_texts"]
