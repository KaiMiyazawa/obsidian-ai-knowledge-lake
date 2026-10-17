from __future__ import annotations

import io
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Literal

from googleapiclient.discovery import Resource
from googleapiclient.http import MediaIoBaseUpload
from mcp.server.fastmcp import FastMCP

from .config import Account, load_accounts
from .gmail import (
    Attachment,
    attachment_parts,
    build_message,
    check_attachment_size,
    decode_base64url,
    find_part,
    headers,
    html_body,
    label_color,
    load_attachment_files,
    make_forward_message,
    make_reply_message,
    merge_draft,
    parse_raw,
    plain_text,
    service_for,
)
from .handles import make_handle, parse_any_handle, parse_handle

MessageFormat = Literal["metadata", "minimal", "plain", "full", "raw"]
LabelListVisibility = Literal["labelShow", "labelShowIfUnread", "labelHide"]
MessageListVisibility = Literal["show", "hide"]

API_FORMAT = {"metadata": "metadata", "minimal": "metadata", "plain": "full", "full": "full"}
SUMMARY_HEADERS = ["From", "To", "Cc", "Bcc", "Subject", "Date"]
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "gmail-unifier"


def _media(message: EmailMessage) -> MediaIoBaseUpload:
    # raw をJSONに入れると5MB前後で弾かれるので、添付25MBまで通るアップロード方式で送る。
    return MediaIoBaseUpload(
        io.BytesIO(message.as_bytes()), mimetype="message/rfc822", resumable=True
    )


def _unique_path(directory: Path, filename: str) -> Path:
    name = Path(filename).name or "attachment"
    candidate = directory / name
    stem, suffix = candidate.stem, candidate.suffix
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def run(config_path: Path) -> None:
    accounts = load_accounts(config_path)
    mcp = FastMCP(
        "gmail-unifier",
        instructions=(
            "複数メールボックスを横断するGmail MCPです。メール・スレッド・下書きは、検索や一覧で得た"
            "署名付きハンドルで指定し、操作は必ずそのハンドルのメールボックスに対して行われます。"
            "返信・転送は受信したメールボックスから送信されます。"
            "送信（send_message / send_reply / forward / send_draft）の前には、必ず宛先・件名・本文を"
            "利用者に示して明示的な許可を得てください。迷ったら下書きを作って見せてください。"
            "完全削除の機能はありません。削除はゴミ箱への移動（trash）です。"
        ),
    )

    def account(account_id: str) -> Account:
        try:
            return accounts[account_id]
        except KeyError as error:
            raise ValueError("未知のアカウントです") from error

    def selected(account_id: str | None) -> list[Account]:
        return [account(account_id)] if account_id else list(accounts.values())

    def check_page_token(page_token: str | None, account_id: str | None) -> None:
        if page_token and not account_id:
            raise ValueError("page_token を使うときは account_id を指定してください")

    def check_limit(value: int) -> None:
        if not 1 <= value <= 100:
            raise ValueError("max_results_per_mailbox は1から100にしてください")

    def mailbox_fields(mailbox: Account) -> dict[str, str]:
        return {"mailbox": mailbox.display_name, "mailbox_address": mailbox.email}

    def get_message(service: Resource, message_id: str, fmt: str) -> dict[str, Any]:
        if fmt == "raw":
            return service.users().messages().get(userId="me", id=message_id, format="raw").execute()
        request: dict[str, Any] = {"userId": "me", "id": message_id, "format": API_FORMAT[fmt]}
        if API_FORMAT[fmt] == "metadata":
            request["metadataHeaders"] = SUMMARY_HEADERS
        return service.users().messages().get(**request).execute()

    def message_view(mailbox: Account, message: dict[str, Any], fmt: str) -> dict[str, Any]:
        """Gmail MCP の messageFormat に合わせて項目を絞ったメッセージ表現。"""
        if fmt == "raw":
            raw = decode_base64url(message["raw"])
            parsed = parse_raw(raw)
            message_headers = {key.lower(): str(value) for key, value in parsed.items()}
        else:
            message_headers = headers(message)
        view: dict[str, Any] = {
            "message_handle": make_handle("message", mailbox.id, message["id"], message["threadId"]),
            "thread_handle": make_handle("thread", mailbox.id, message["threadId"]),
            **mailbox_fields(mailbox),
            "from": message_headers.get("from", ""),
            "to": message_headers.get("to", ""),
            "cc": message_headers.get("cc", ""),
            "bcc": message_headers.get("bcc", ""),
            "date": message_headers.get("date", ""),
            "label_ids": message.get("labelIds", []),
        }
        if fmt != "metadata":
            view["subject"] = message_headers.get("subject", "")
            view["snippet"] = message.get("snippet", "")
        if fmt in ("plain", "full"):
            payload = message.get("payload", {})
            view["body"] = plain_text(payload)
            view["attachments"] = attachment_parts(payload)
            if fmt == "full":
                view["html_body"] = html_body(payload)
        if fmt == "raw":
            view["raw"] = raw.decode("utf-8", "replace")
        return view

    def attachment_data(service: Resource, message: dict[str, Any], part: dict[str, Any]) -> bytes:
        body = part.get("body", {})
        if body.get("data"):
            return decode_base64url(body["data"])
        fetched = service.users().messages().attachments().get(
            userId="me", messageId=message["id"], id=body["attachmentId"]
        ).execute()
        return decode_base64url(fetched["data"])

    def original_attachments(service: Resource, message: dict[str, Any]) -> list[Attachment]:
        payload = message.get("payload", {})
        attachments: list[Attachment] = []
        for item in attachment_parts(payload):
            part = find_part(payload, item["part_id"])
            if part is not None:
                attachments.append(
                    (item["filename"], attachment_data(service, message, part), item["mime_type"])
                )
        check_attachment_size(attachments)
        return attachments

    def handle_target(handle: str) -> tuple[Account, str, str]:
        """メッセージかスレッドのハンドルを (メールボックス, 種類, ID) にする。"""
        payload = parse_any_handle(handle, ("message", "thread"))
        return account(payload["a"]), payload["k"], payload["i"]

    def apply_to_handles(
        handles: list[str], operation: Callable[[Resource, str, str], None]
    ) -> list[dict[str, str]]:
        if not handles:
            raise ValueError("handles を1件以上指定してください")
        targets = [handle_target(handle) for handle in handles]  # 先に全件を検証してから変更する
        results = []
        for mailbox, kind, resource_id in targets:
            operation(service_for(mailbox), kind, resource_id)
            results.append({**mailbox_fields(mailbox), "kind": kind, "id": resource_id})
        return results

    def modify(service: Resource, kind: str, resource_id: str, add: list[str], remove: list[str]):
        resource = service.users().messages() if kind == "message" else service.users().threads()
        resource.modify(
            userId="me", id=resource_id, body={"addLabelIds": add, "removeLabelIds": remove}
        ).execute()

    def draft_summary(mailbox: Account, draft: dict[str, Any], fmt: str) -> dict[str, Any]:
        message = draft.get("message", {})
        view = message_view(mailbox, message, fmt) if fmt else {}
        view.pop("message_handle", None)
        return {
            "draft_handle": make_handle("draft", mailbox.id, draft["id"], message.get("threadId")),
            **view,
        }

    def resolve_mailbox(account_id: str | None, reply_handle: str | None) -> tuple[Account, Any]:
        """送信元を決める。返信先ハンドルがあれば、そのメールボックスに固定する。"""
        if reply_handle:
            handle = parse_handle(reply_handle, "message")
            mailbox = account(handle["a"])
            if account_id and account_id != mailbox.id:
                raise ValueError("返信先メールと異なるメールボックスからは送れません")
            return mailbox, handle
        if not account_id:
            raise ValueError("account_id を指定してください（返信でない新規メール）")
        return account(account_id), None

    def compose(
        service: Resource,
        mailbox: Account,
        reply: Any,
        *,
        to: list[str] | None,
        cc: list[str] | None,
        bcc: list[str] | None,
        subject: str,
        body: str | None,
        html: str | None,
        attachment_paths: list[str] | None,
        reply_all: bool,
        include_quote: bool,
    ) -> tuple[EmailMessage, str | None]:
        attachments = load_attachment_files(attachment_paths or [])
        if reply is None:
            if not (to or cc or bcc):
                raise ValueError("宛先（to / cc / bcc）を指定してください")
            message = build_message(
                to=to, cc=cc, bcc=bcc, subject=subject, body=body, html=html,
                attachments=attachments,
            )
            return message, None
        original = service.users().messages().get(userId="me", id=reply["i"], format="full").execute()
        message = make_reply_message(
            original, mailbox.email, body or "", reply_all, html=html, to=to, cc=cc, bcc=bcc,
            attachments=attachments, include_quote=include_quote,
        )
        if subject:
            del message["Subject"]
            message["Subject"] = subject
        if not (message["To"] or message["Cc"] or message["Bcc"]):
            raise ValueError("返信先が決まりません。to を指定してください")
        return message, original["threadId"]

    def sent_result(mailbox: Account, sent: dict[str, Any], message: EmailMessage) -> dict[str, Any]:
        return {
            "status": "送信しました",
            "from": mailbox.email,
            "to": str(message["To"] or ""),
            "cc": str(message["Cc"] or ""),
            "subject": str(message["Subject"] or ""),
            "message_handle": make_handle("message", mailbox.id, sent["id"], sent["threadId"]),
            "label_ids": sent.get("labelIds", []),
        }

    # ---- メールボックス・検索・閲覧 ----

    @mcp.tool()
    def list_mailboxes() -> list[dict[str, str]]:
        """利用可能なメールボックスを一覧する。"""
        return [
            {"account_id": item.id, "email": item.email, "display_name": item.display_name}
            for item in accounts.values()
        ]

    @mcp.tool()
    def search_mail(
        query: str,
        account_id: str | None = None,
        max_results_per_mailbox: int = 20,
        include_spam_and_trash: bool = False,
    ) -> list[dict[str, Any]]:
        """全メールボックス、または指定メールボックスのGmail検索をメッセージ単位で行う。アーカイブも標準で対象。"""
        check_limit(max_results_per_mailbox)
        results: list[dict[str, Any]] = []
        for mailbox in selected(account_id):
            service = service_for(mailbox)
            listing = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_results_per_mailbox,
                includeSpamTrash=include_spam_and_trash,
            ).execute()
            for item in listing.get("messages", []):
                message = get_message(service, item["id"], "minimal")
                view = message_view(mailbox, message, "minimal")
                view.pop("bcc")
                results.append(view)
        return results

    @mcp.tool()
    def search_threads(
        query: str = "",
        account_id: str | None = None,
        max_results_per_mailbox: int = 20,
        include_spam_and_trash: bool = False,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """スレッド単位でGmail検索する。各スレッドのメッセージ一覧（件名・送信者・スニペット）付き。

        次ページは返された next_page_tokens の値を page_token に、対応する account_id と一緒に渡す。
        """
        check_limit(max_results_per_mailbox)
        check_page_token(page_token, account_id)
        threads: list[dict[str, Any]] = []
        next_tokens: dict[str, str] = {}
        for mailbox in selected(account_id):
            service = service_for(mailbox)
            listing = service.users().threads().list(
                userId="me",
                q=query,
                maxResults=max_results_per_mailbox,
                includeSpamTrash=include_spam_and_trash,
                pageToken=page_token,
            ).execute()
            if listing.get("nextPageToken"):
                next_tokens[mailbox.id] = listing["nextPageToken"]
            for item in listing.get("threads", []):
                thread = service.users().threads().get(
                    userId="me", id=item["id"], format="metadata", metadataHeaders=SUMMARY_HEADERS
                ).execute()
                threads.append(
                    {
                        "thread_handle": make_handle("thread", mailbox.id, item["id"]),
                        **mailbox_fields(mailbox),
                        "messages": [
                            message_view(mailbox, message, "minimal")
                            for message in thread.get("messages", [])
                        ],
                    }
                )
        return {"threads": threads, "next_page_tokens": next_tokens}

    @mcp.tool()
    def read_message(message_handle: str, format: MessageFormat = "plain") -> dict[str, Any]:
        """メール1通を読む。

        format: metadata=宛先・日時・ラベルのみ / minimal=件名とスニペットまで /
        plain=本文テキストと添付一覧（推奨） / full=plainにHTML本文も追加 / raw=MIME原文
        """
        handle = parse_handle(message_handle, "message")
        mailbox = account(handle["a"])
        return message_view(mailbox, get_message(service_for(mailbox), handle["i"], format), format)

    @mcp.tool()
    def get_thread(thread_handle: str, format: MessageFormat = "plain") -> dict[str, Any]:
        """スレッド全体（下書きを除く）を読む。format は read_message と同じ（raw は不可）。"""
        if format == "raw":
            raise ValueError("スレッドでは raw は使えません。read_message で1通ずつ取得してください")
        handle = parse_handle(thread_handle, "thread")
        mailbox = account(handle["a"])
        request: dict[str, Any] = {"userId": "me", "id": handle["i"], "format": API_FORMAT[format]}
        if API_FORMAT[format] == "metadata":
            request["metadataHeaders"] = SUMMARY_HEADERS
        thread = service_for(mailbox).users().threads().get(**request).execute()
        return {
            "thread_handle": thread_handle,
            **mailbox_fields(mailbox),
            "messages": [
                message_view(mailbox, message, format)
                for message in thread.get("messages", [])
                if "DRAFT" not in message.get("labelIds", [])
            ],
        }

    @mcp.tool()
    def download_attachment(
        message_handle: str, part_id: str, output_dir: str | None = None
    ) -> dict[str, Any]:
        """添付ファイルをローカルに保存する。part_id は read_message の attachments から取る。

        既定の保存先は ~/Downloads/gmail-unifier/。同名ファイルは上書きせず番号を付ける。
        """
        handle = parse_handle(message_handle, "message")
        mailbox = account(handle["a"])
        service = service_for(mailbox)
        message = service.users().messages().get(userId="me", id=handle["i"], format="full").execute()
        part = find_part(message.get("payload", {}), part_id)
        if part is None or not part.get("filename"):
            raise ValueError("その part_id の添付ファイルはありません")
        directory = Path(output_dir).expanduser() if output_dir else DEFAULT_DOWNLOAD_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = _unique_path(directory, part["filename"])
        data = attachment_data(service, message, part)
        path.write_bytes(data)
        return {"path": str(path), "filename": part["filename"], "size": len(data)}

    # ---- ラベル ----

    @mcp.tool()
    def list_labels(account_id: str | None = None) -> list[dict[str, Any]]:
        """ラベルを一覧する。ラベルIDはメールボックスごとに異なるので、操作対象と同じメールボックスのIDを使う。"""
        results = []
        for mailbox in selected(account_id):
            listing = service_for(mailbox).users().labels().list(userId="me").execute()
            for label in listing.get("labels", []):
                results.append(
                    {
                        "account_id": mailbox.id,
                        "label_id": label["id"],
                        "name": label["name"],
                        "type": label.get("type", ""),
                        "color": label.get("color"),
                        "label_list_visibility": label.get("labelListVisibility"),
                        "message_list_visibility": label.get("messageListVisibility"),
                    }
                )
        return results

    @mcp.tool()
    def create_label(
        account_id: str,
        name: str,
        color: str | None = None,
        label_list_visibility: LabelListVisibility | None = None,
        message_list_visibility: MessageListVisibility | None = None,
        auto_create_parent_labels: bool = True,
    ) -> dict[str, Any]:
        """ラベルを作る。"親/子" で入れ子にでき、既定では無い親ラベルも作る。

        color: black, dark_gray, gray, light_gray, white, red, orange, yellow, green, mint,
        teal, blue, purple, pink, dark_red, dark_orange, dark_green, dark_blue, dark_purple,
        dark_pink, brown
        """
        mailbox = account(account_id)
        labels = service_for(mailbox).users().labels()
        existing = {label["name"] for label in labels.list(userId="me").execute().get("labels", [])}
        if name in existing:
            raise ValueError(f"同名のラベルが既にあります: {name}")
        created_parents = []
        parts = name.split("/")
        for depth in range(1, len(parts)):
            parent = "/".join(parts[:depth])
            if parent in existing:
                continue
            if not auto_create_parent_labels:
                raise ValueError(f"親ラベルがありません: {parent}")
            labels.create(userId="me", body={"name": parent}).execute()
            created_parents.append(parent)
        body: dict[str, Any] = {"name": name}
        if color:
            body["color"] = label_color(color)
        if label_list_visibility:
            body["labelListVisibility"] = label_list_visibility
        if message_list_visibility:
            body["messageListVisibility"] = message_list_visibility
        created = labels.create(userId="me", body=body).execute()
        return {
            "account_id": mailbox.id,
            "label_id": created["id"],
            "name": created["name"],
            "created_parent_labels": created_parents,
        }

    @mcp.tool()
    def update_label(
        account_id: str,
        label_id: str,
        name: str | None = None,
        color: str | None = None,
        label_list_visibility: LabelListVisibility | None = None,
        message_list_visibility: MessageListVisibility | None = None,
    ) -> dict[str, Any]:
        """ラベルの名前・色・表示設定を変える。指定しなかった項目は保つ。color は create_label と同じ。"""
        body: dict[str, Any] = {}
        if name:
            body["name"] = name
        if color:
            body["color"] = label_color(color)
        if label_list_visibility:
            body["labelListVisibility"] = label_list_visibility
        if message_list_visibility:
            body["messageListVisibility"] = message_list_visibility
        if not body:
            raise ValueError("変更する項目を1つ以上指定してください")
        mailbox = account(account_id)
        updated = service_for(mailbox).users().labels().patch(
            userId="me", id=label_id, body=body
        ).execute()
        return {"account_id": mailbox.id, "label_id": updated["id"], "name": updated["name"]}

    @mcp.tool()
    def delete_label(account_id: str, label_id: str) -> dict[str, str]:
        """ラベルを削除する。メール自体は消えず、ラベルが外れるだけ。システムラベルは消せない。"""
        mailbox = account(account_id)
        service_for(mailbox).users().labels().delete(userId="me", id=label_id).execute()
        return {"status": "ラベルを削除しました", "account_id": mailbox.id, "label_id": label_id}

    @mcp.tool()
    def modify_labels(
        handles: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """メッセージまたはスレッドのラベルを付け外しする（複数件可）。

        handles には message_handle と thread_handle を混ぜてよい。スレッドに付けると中の全メールに付く。
        システムラベルも使える: INBOX（外すとアーカイブ）, UNREAD（外すと既読）, STARRED, IMPORTANT。
        ゴミ箱・迷惑メールは trash / mark_spam を使う。
        """
        add, remove = add_label_ids or [], remove_label_ids or []
        if not (add or remove):
            raise ValueError("add_label_ids か remove_label_ids を指定してください")
        return apply_to_handles(
            handles, lambda service, kind, item: modify(service, kind, item, add, remove)
        )

    # ---- ゴミ箱・迷惑メール ----

    @mcp.tool()
    def trash(handles: list[str]) -> list[dict[str, str]]:
        """メッセージまたはスレッドをゴミ箱へ移す（複数件可）。30日後にGmailが自動で消す。完全削除はしない。"""

        def operation(service: Resource, kind: str, item: str) -> None:
            resource = service.users().messages() if kind == "message" else service.users().threads()
            resource.trash(userId="me", id=item).execute()

        return apply_to_handles(handles, operation)

    @mcp.tool()
    def untrash(handles: list[str]) -> list[dict[str, str]]:
        """ゴミ箱から戻す（複数件可）。ゴミ箱内のメールは search_* で include_spam_and_trash=True にすると見つかる。"""

        def operation(service: Resource, kind: str, item: str) -> None:
            resource = service.users().messages() if kind == "message" else service.users().threads()
            resource.untrash(userId="me", id=item).execute()

        return apply_to_handles(handles, operation)

    @mcp.tool()
    def mark_spam(handles: list[str]) -> list[dict[str, str]]:
        """迷惑メールにする（複数件可）。受信トレイからは外れる。"""
        return apply_to_handles(
            handles, lambda service, kind, item: modify(service, kind, item, ["SPAM"], ["INBOX"])
        )

    @mcp.tool()
    def unmark_spam(handles: list[str]) -> list[dict[str, str]]:
        """迷惑メールを解除し、受信トレイに戻す（複数件可）。"""
        return apply_to_handles(
            handles, lambda service, kind, item: modify(service, kind, item, ["INBOX"], ["SPAM"])
        )

    # ---- 下書き ----

    @mcp.tool()
    def list_drafts(
        account_id: str | None = None,
        query: str | None = None,
        max_results_per_mailbox: int = 20,
        page_token: str | None = None,
        include_content: bool = False,
    ) -> dict[str, Any]:
        """下書きを一覧する。include_content=True で件名・本文も返す（既定は宛先と日時のみ）。"""
        check_limit(max_results_per_mailbox)
        check_page_token(page_token, account_id)
        drafts: list[dict[str, Any]] = []
        next_tokens: dict[str, str] = {}
        for mailbox in selected(account_id):
            service = service_for(mailbox)
            listing = service.users().drafts().list(
                userId="me", q=query, maxResults=max_results_per_mailbox, pageToken=page_token
            ).execute()
            if listing.get("nextPageToken"):
                next_tokens[mailbox.id] = listing["nextPageToken"]
            fmt = "plain" if include_content else "metadata"
            for item in listing.get("drafts", []):
                draft = service.users().drafts().get(
                    userId="me", id=item["id"], format=API_FORMAT[fmt]
                ).execute()
                drafts.append(draft_summary(mailbox, draft, fmt))
        return {"drafts": drafts, "next_page_tokens": next_tokens}

    @mcp.tool()
    def get_draft(draft_handle: str, format: MessageFormat = "plain") -> dict[str, Any]:
        """下書き1件を読む。format は read_message と同じ。"""
        handle = parse_handle(draft_handle, "draft")
        mailbox = account(handle["a"])
        api_format = "raw" if format == "raw" else API_FORMAT[format]
        draft = service_for(mailbox).users().drafts().get(
            userId="me", id=handle["i"], format=api_format
        ).execute()
        return draft_summary(mailbox, draft, format)

    @mcp.tool()
    def create_draft(
        account_id: str | None = None,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        subject: str = "",
        body: str | None = None,
        html_body: str | None = None,
        attachment_paths: list[str] | None = None,
        reply_to_message_handle: str | None = None,
        reply_all: bool = False,
        include_quote: bool = True,
    ) -> dict[str, Any]:
        """下書きを作る（新規または返信）。送信はしない。

        新規は account_id と宛先が必要。reply_to_message_handle を渡すと返信になり、送信元は
        そのメールのメールボックスに固定、宛先・件名・スレッドは元メールから決まる（to/cc/bcc/subject
        を渡すと上書き）。include_quote で元メールを引用する。body はMarkdownにしない。
        attachment_paths はローカルファイルのパス（合計25MBまで）。
        """
        mailbox, reply = resolve_mailbox(account_id, reply_to_message_handle)
        service = service_for(mailbox)
        message, thread_id = compose(
            service, mailbox, reply, to=to, cc=cc, bcc=bcc, subject=subject, body=body,
            html=html_body, attachment_paths=attachment_paths, reply_all=reply_all,
            include_quote=include_quote,
        )
        draft_body: dict[str, Any] = {"message": {"threadId": thread_id} if thread_id else {}}
        created = service.users().drafts().create(
            userId="me", body=draft_body, media_body=_media(message)
        ).execute()
        return {
            "draft_handle": make_handle("draft", mailbox.id, created["id"], thread_id),
            "from": mailbox.email,
            "to": str(message["To"] or ""),
            "cc": str(message["Cc"] or ""),
            "bcc": str(message["Bcc"] or ""),
            "subject": str(message["Subject"] or ""),
            "attachments": [Path(path).name for path in attachment_paths or []],
            "status": "下書きのみ作成済み。本人の確認後に send_draft を呼んでください。",
        }

    @mcp.tool()
    def create_reply_draft(message_handle: str, body: str, reply_all: bool = False) -> dict[str, Any]:
        """受信メールへの返信下書きを作る（引用なしの簡易版）。送信元は受信したメールボックスに固定。"""
        result = create_draft(
            reply_to_message_handle=message_handle, body=body, reply_all=reply_all,
            include_quote=False,
        )
        return {**result, "body": body}

    @mcp.tool()
    def update_draft(
        draft_handle: str,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        subject: str | None = None,
        body: str | None = None,
        html_body: str | None = None,
        attachment_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """下書きを部分更新する。渡した項目だけ置き換え、渡さない項目は保つ。

        本文は body / html_body のどちらかを渡すと両方を置き換える。添付は attachment_paths を
        渡したときだけ置き換え（[] で全部外す）、渡さなければ既存の添付を残す。
        """
        handle = parse_handle(draft_handle, "draft")
        mailbox = account(handle["a"])
        service = service_for(mailbox)
        current = service.users().drafts().get(userId="me", id=handle["i"], format="raw").execute()
        existing = parse_raw(decode_base64url(current["message"]["raw"]))
        attachments = None if attachment_paths is None else load_attachment_files(attachment_paths)
        message = merge_draft(
            existing, to=to, cc=cc, bcc=bcc, subject=subject, body=body, html=html_body,
            attachments=attachments,
        )
        thread_id = current["message"].get("threadId")
        updated = service.users().drafts().update(
            userId="me",
            id=handle["i"],
            body={"id": handle["i"], "message": {"threadId": thread_id} if thread_id else {}},
            media_body=_media(message),
        ).execute()
        return {
            "draft_handle": make_handle("draft", mailbox.id, updated["id"], thread_id),
            "from": mailbox.email,
            "to": str(message["To"] or ""),
            "cc": str(message["Cc"] or ""),
            "bcc": str(message["Bcc"] or ""),
            "subject": str(message["Subject"] or ""),
            "attachments": [part.get_filename() for part in message.iter_attachments()],
            "status": "下書きを更新しました。送信はしていません。",
        }

    @mcp.tool()
    def delete_draft(draft_handle: str) -> dict[str, str]:
        """下書きを削除する（Gmailの下書き破棄と同じで、ゴミ箱には入らない）。"""
        handle = parse_handle(draft_handle, "draft")
        mailbox = account(handle["a"])
        service_for(mailbox).users().drafts().delete(userId="me", id=handle["i"]).execute()
        return {"status": "下書きを削除しました", "from": mailbox.email}

    # ---- 送信（すべて本人の明示的な許可を得てから呼ぶ） ----

    @mcp.tool()
    def send_draft(draft_handle: str) -> dict[str, Any]:
        """確認済みの下書きを送信する。下書きのあるメールボックスからのみ送信される。"""
        handle = parse_handle(draft_handle, "draft")
        mailbox = account(handle["a"])
        service = service_for(mailbox)
        current = service.users().drafts().get(userId="me", id=handle["i"], format="raw").execute()
        message = parse_raw(decode_base64url(current["message"]["raw"]))
        sent = service.users().drafts().send(userId="me", body={"id": handle["i"]}).execute()
        return sent_result(mailbox, sent, message)

    @mcp.tool()
    def send_message(
        account_id: str | None = None,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        subject: str = "",
        body: str | None = None,
        html_body: str | None = None,
        attachment_paths: list[str] | None = None,
        reply_to_message_handle: str | None = None,
        reply_all: bool = False,
        include_quote: bool = True,
    ) -> dict[str, Any]:
        """メールを即時送信する（下書きを経由しない）。引数は create_draft と同じ。

        送信前に宛先・件名・本文を本人に示し、明示的な許可を得ること。
        """
        mailbox, reply = resolve_mailbox(account_id, reply_to_message_handle)
        service = service_for(mailbox)
        message, thread_id = compose(
            service, mailbox, reply, to=to, cc=cc, bcc=bcc, subject=subject, body=body,
            html=html_body, attachment_paths=attachment_paths, reply_all=reply_all,
            include_quote=include_quote,
        )
        sent = service.users().messages().send(
            userId="me", body={"threadId": thread_id} if thread_id else {}, media_body=_media(message)
        ).execute()
        return sent_result(mailbox, sent, message)

    @mcp.tool()
    def send_reply(
        message_handle: str,
        body: str | None = None,
        html_body: str | None = None,
        reply_all: bool = False,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachment_paths: list[str] | None = None,
        include_quote: bool = True,
    ) -> dict[str, Any]:
        """受信メールに即時返信する。送信元は受信したメールボックスに固定。送信前に本人の許可を得ること。"""
        if not (body or html_body):
            raise ValueError("body か html_body を指定してください")
        return send_message(
            to=to, cc=cc, bcc=bcc, body=body, html_body=html_body,
            attachment_paths=attachment_paths, reply_to_message_handle=message_handle,
            reply_all=reply_all, include_quote=include_quote,
        )

    @mcp.tool()
    def forward(
        message_handle: str,
        to: list[str],
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        text: str = "",
        html_body: str | None = None,
        include_attachments: bool = True,
    ) -> dict[str, Any]:
        """メールを転送する（即時送信）。送信元は受信したメールボックスに固定。元の添付も既定で付ける。

        送信前に宛先とコメントを本人に示し、明示的な許可を得ること。
        """
        if not to:
            raise ValueError("転送先 to を指定してください")
        handle = parse_handle(message_handle, "message")
        mailbox = account(handle["a"])
        service = service_for(mailbox)
        original = service.users().messages().get(userId="me", id=handle["i"], format="full").execute()
        message = make_forward_message(
            original, to=to, cc=cc, bcc=bcc, text=text, html=html_body,
            attachments=original_attachments(service, original) if include_attachments else [],
        )
        sent = service.users().messages().send(userId="me", body={}, media_body=_media(message)).execute()
        return sent_result(mailbox, sent, message)

    mcp.run(transport="stdio")
