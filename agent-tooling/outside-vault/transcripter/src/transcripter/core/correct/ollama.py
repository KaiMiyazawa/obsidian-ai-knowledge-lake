"""ローカル Ollama による後補正（外部送信なし・localhost のみ）。

事前準備:
  1. Ollama を導入（https://ollama.com）
  2. 日本語に強いモデルを取得（例: `ollama pull qwen2.5:7b`）
  3. `--llm-correct`（既定 backend=ollama）で有効化
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ...errors import TranscripterError
from .prompt import SYSTEM_PROMPT, build_user_prompt, parse_response


class OllamaCorrector:
    name = "ollama"

    def __init__(self, model: str, endpoint: str = "http://localhost:11434") -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")

    def correct_batch(
        self, texts: list[str], glossary: list[tuple[str, str]]
    ) -> list[str] | None:
        body = {
            "model": self.model,
            "prompt": build_user_prompt(texts, glossary),
            "system": SYSTEM_PROMPT,
            "stream": False,
            "format": "json",       # JSON オブジェクトを強制
            "options": {"temperature": 0},
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.endpoint}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise TranscripterError(
                f"Ollama に接続できません（{self.endpoint}）: {exc}\n"
                "  Ollama を起動し、モデルを取得してください: ollama pull "
                f"{self.model}"
            ) from exc
        return parse_response(payload.get("response", ""), len(texts))
