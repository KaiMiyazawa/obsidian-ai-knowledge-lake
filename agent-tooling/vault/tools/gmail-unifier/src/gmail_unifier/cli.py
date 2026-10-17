from __future__ import annotations

import argparse
from pathlib import Path

import keyring
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import APP_NAME, default_config_path, load_accounts
from .gmail import SCOPES, credential_name, credentials_for, service_for
from .server import run


def authorize(account_id: str, client_secrets: Path, config_path: Path | None) -> None:
    accounts = load_accounts(config_path)
    if account_id not in accounts:
        raise ValueError(f"未定義のアカウントIDです: {account_id}")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    credentials = flow.run_local_server(
        port=0,
        open_browser=True,
        # 既存の同意を使い回さず、必ず新しい範囲でリフレッシュトークンを取り直す。
        prompt="consent",
        login_hint=accounts[account_id].email,
    )
    keyring.set_password(APP_NAME, credential_name(account_id), credentials.to_json())
    print(f"認証を保存しました: {accounts[account_id].display_name}")


def status(config_path: Path | None) -> None:
    """各メールボックスの認可範囲と、実際にGmail APIへ届くかを表示する。"""
    for account in load_accounts(config_path).values():
        try:
            scopes = credentials_for(account).scopes or []
            profile = service_for(account).users().getProfile(userId="me").execute()
            full = "全権限" if set(SCOPES) <= set(scopes) else "要再認可"
            print(f"{account.display_name}: OK {profile['emailAddress']} [{full}] {' '.join(scopes)}")
        except Exception as error:  # noqa: BLE001 - 1件の失敗で他のアカウントの確認を止めない
            print(f"{account.display_name}: NG {account.email} {type(error).__name__}: {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-account Gmail MCP")
    parser.add_argument("--config", type=Path, default=default_config_path())
    subcommands = parser.add_subparsers(dest="command", required=True)
    auth_parser = subcommands.add_parser("authorize")
    auth_parser.add_argument("account_id")
    auth_parser.add_argument("--client-secrets", type=Path, required=True)
    subcommands.add_parser("serve")
    subcommands.add_parser("status")
    args = parser.parse_args()
    if args.command == "authorize":
        authorize(args.account_id, args.client_secrets, args.config)
    elif args.command == "status":
        status(args.config)
    else:
        run(args.config)


if __name__ == "__main__":
    main()
