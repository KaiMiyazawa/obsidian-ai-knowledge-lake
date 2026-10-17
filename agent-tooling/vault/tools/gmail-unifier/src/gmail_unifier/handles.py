from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets

import keyring

from .config import APP_NAME

HANDLE_KEY_NAME = "handle-signing-key-v1"


def _key() -> bytes:
    encoded = keyring.get_password(APP_NAME, HANDLE_KEY_NAME)
    if encoded is None:
        encoded = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
        keyring.set_password(APP_NAME, HANDLE_KEY_NAME, encoded)
    return base64.urlsafe_b64decode(encoded.encode("ascii"))


def make_handle(kind: str, account_id: str, resource_id: str, thread_id: str | None = None) -> str:
    payload = {"a": account_id, "i": resource_id, "k": kind}
    if thread_id is not None:
        payload["t"] = thread_id
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(_key(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


def parse_handle(handle: str, expected_kind: str) -> dict[str, str]:
    return parse_any_handle(handle, (expected_kind,))


def parse_any_handle(handle: str, kinds: tuple[str, ...]) -> dict[str, str]:
    """署名を検証し、種類が kinds のいずれかであるハンドルの中身を返す。"""
    try:
        encoded, supplied_signature = handle.split(".", maxsplit=1)
        expected_signature = base64.urlsafe_b64encode(
            hmac.new(_key(), encoded.encode("ascii"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError("署名が一致しません")
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode((encoded + padding).encode("ascii")))
        if payload["k"] not in kinds:
            raise ValueError("この操作には使えないハンドルです")
        return payload
    except (KeyError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("無効なハンドルです") from error
