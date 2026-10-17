"""後補正プロンプトの組み立てと応答パース。"""

from __future__ import annotations

import json

SYSTEM_PROMPT = (
    "あなたは日本語の文字起こし校正者です。各行は音声認識(ASR)の出力で、"
    "同音異義語・固有名詞・数字・句読点に誤りを含むことがあります。\n"
    "ルール:\n"
    "1. 明らかな誤変換・誤認識・句読点のみを、文脈に基づいて最小限修正する。\n"
    "2. 言い換え・要約・情報の追加や削除は禁止。話し言葉の口調・フィラーは残す。\n"
    "3. 行数・順序を厳密に維持し、入力の各行に出力の各行を1対1で対応させる。\n"
    "4. 用語集が与えられたら、その表記に必ず合わせる。\n"
    "5. 迷ったら原文のままにする（過剰修正を避ける）。\n"
    '出力は {"lines": ["...", "..."]} という JSON オブジェクトのみ。'
    "説明文は一切書かない。"
)


def build_user_prompt(texts: list[str], glossary: list[tuple[str, str]]) -> str:
    """補正対象の行と用語集を含むユーザープロンプトを作る。"""
    parts: list[str] = []
    if glossary:
        gl = "\n".join(f"- 「{a}」→「{b}」" for a, b in glossary)
        parts.append("用語集（誤り→正しい表記）:\n" + gl)
    payload = {"lines": list(texts)}
    parts.append(
        "次の JSON の各 line を上記ルールで補正し、同じ行数の JSON で返してください:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    return "\n\n".join(parts)


def parse_response(content: str, expected: int) -> list[str] | None:
    """モデル応答から補正済み行配列を取り出す。件数不一致・失敗時は None。"""
    content = content.strip()
    # ```json フェンスなどを除去
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        # オブジェクトの前後にテキストが混ざる場合、最初の { … } を拾う
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(content[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            return None
    lines = data.get("lines") if isinstance(data, dict) else None
    if not isinstance(lines, list) or len(lines) != expected:
        return None
    return [str(x) for x in lines]
