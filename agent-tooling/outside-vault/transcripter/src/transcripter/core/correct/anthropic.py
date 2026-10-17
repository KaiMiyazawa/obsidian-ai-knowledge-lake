"""外部 API（Anthropic Claude）による後補正。★オプトイン（外部送信あり）。

有効化すると **音声由来のテキストが Anthropic のサーバへ送信される**。
ローカル完結の原則から外れるため、既定では使わない。利用時は精度は最も高い。
API キーは --llm-api-key か環境変数 ANTHROPIC_API_KEY。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ...errors import TranscripterError
from ...logging_conf import get_logger
from .prompt import SYSTEM_PROMPT, build_user_prompt, parse_response

logger = get_logger()

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"


class AnthropicCorrector:
    name = "anthropic"

    def __init__(self, model: str, api_key: str = "") -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise TranscripterError(
                "外部API後補正には API キーが必要です。"
                "--llm-api-key か環境変数 ANTHROPIC_API_KEY を設定してください。"
            )
        # 外部送信の明示警告（ローカル完結から外れる）。
        logger.warning(
            "⚠ 外部API後補正が有効です: 認識テキストを Anthropic (%s) へ送信します。",
            self.model,
        )

    def correct_batch(
        self, texts: list[str], glossary: list[tuple[str, str]]
    ) -> list[str] | None:
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": build_user_prompt(texts, glossary)}
            ],
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            _API_URL,
            data=data,
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": _API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise TranscripterError(
                f"Anthropic API エラー（{exc.code}）: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise TranscripterError(f"Anthropic API に接続できません: {exc}") from exc
        blocks = payload.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return parse_response(text, len(texts))
