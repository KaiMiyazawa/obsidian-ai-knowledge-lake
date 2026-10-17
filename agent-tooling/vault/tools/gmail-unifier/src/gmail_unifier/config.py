from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "gmail-unifier"


@dataclass(frozen=True)
class Account:
    id: str
    email: str
    display_name: str


def default_config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME / "config.toml"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME / "config.toml"


def load_accounts(path: Path | None = None) -> dict[str, Account]:
    path = path or default_config_path()
    if not path.exists():
        raise FileNotFoundError(f"設定がありません: {path}")
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    accounts: dict[str, Account] = {}
    for item in raw.get("accounts", []):
        account = Account(
            id=str(item["id"]),
            email=str(item["email"]),
            display_name=str(item.get("display_name", item["id"])),
        )
        if account.id in accounts:
            raise ValueError(f"重複したアカウントIDです: {account.id}")
        accounts[account.id] = account
    if not accounts:
        raise ValueError("accounts を少なくとも1件設定してください")
    return accounts
