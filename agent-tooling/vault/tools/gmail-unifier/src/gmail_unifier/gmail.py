from __future__ import annotations

import base64
import json
import mimetypes
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import keyring
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

from .config import APP_NAME, Account

# 2026-10-01、再認可を最後にするため全権限にした（本人判断）。ツールとしては完全削除を提供しない。
SCOPES = ["https://mail.google.com/"]

# Gmail API が受け付けるパレット内の色（背景, 文字）。Gmail MCP の color preset と同じ組。
LABEL_COLOR_PRESETS = {
    "black": ("#000000", "#ffffff"),
    "dark_gray": ("#434343", "#ffffff"),
    "gray": ("#666666", "#ffffff"),
    "light_gray": ("#cccccc", "#000000"),
    "white": ("#ffffff", "#000000"),
    "red": ("#fb4c2f", "#ffffff"),
    "orange": ("#ffad47", "#000000"),
    "yellow": ("#fad165", "#000000"),
    "green": ("#16a765", "#ffffff"),
    "mint": ("#43d692", "#000000"),
    "teal": ("#2da2bb", "#ffffff"),
    "blue": ("#4a86e8", "#ffffff"),
    "purple": ("#a479e2", "#ffffff"),
    "pink": ("#f691b2", "#000000"),
    "dark_red": ("#822111", "#ffffff"),
    "dark_orange": ("#a46a21", "#ffffff"),
    "dark_green": ("#076239", "#ffffff"),
    "dark_blue": ("#1c4587", "#ffffff"),
    "dark_purple": ("#41236d", "#ffffff"),
    "dark_pink": ("#83334c", "#ffffff"),
    "brown": ("#7a4706", "#ffffff"),
}

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024

Attachment = tuple[str, bytes, str]  # (ファイル名, 中身, MIMEタイプ)


def credential_name(account_id: str) -> str:
    return f"oauth-credentials-v1:{account_id}"


def credentials_for(account: Account) -> Credentials:
    serialized = keyring.get_password(APP_NAME, credential_name(account.id))
    if serialized is None:
        raise RuntimeError(f"{account.display_name}（{account.email}）が未認証です")
    # 範囲はトークン自身が持つものを使う。再認可前の旧トークン（readonly+compose）も壊さない。
    return Credentials.from_authorized_user_info(json.loads(serialized))


def service_for(account: Account) -> Resource:
    return build("gmail", "v1", credentials=credentials_for(account), cache_discovery=False)


def label_color(preset: str) -> dict[str, str]:
    try:
        background, text = LABEL_COLOR_PRESETS[preset.lower()]
    except KeyError as error:
        raise ValueError(f"未知の色です。使える色: {', '.join(LABEL_COLOR_PRESETS)}") from error
    return {"backgroundColor": background, "textColor": text}


def headers(message: dict[str, Any]) -> dict[str, str]:
    return {
        str(header["name"]).lower(): str(header["value"])
        for header in message.get("payload", {}).get("headers", [])
    }


class _HTMLText(HTMLParser):
    BLOCKS = frozenset({"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"})

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.chunks.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href")
            if href and href.startswith("http"):
                self.chunks.append(f" <{href}> ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.chunks.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    lines = (" ".join(line.split()) for line in "".join(parser.chunks).splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _charset(part: dict[str, Any]) -> str:
    for header in part.get("headers", []):
        if str(header.get("name", "")).lower() == "content-type":
            match = re.search(r'charset="?([^";\s]+)', str(header.get("value", "")), re.IGNORECASE)
            if match:
                return match.group(1)
    return "utf-8"


def _decoded_parts(payload: dict[str, Any], mime_type: str) -> list[str]:
    body = payload.get("body", {}).get("data")
    if payload.get("mimeType", "") == mime_type and body:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        # Gmail API は ISO-2022-JP などの本文を UTF-8 に変換して返すことがあり、
        # ヘッダーの charset と実際のバイト列が食い違う。ESC を含まず UTF-8 として
        # 正しく読めるならそちらを採る（ISO-2022-JP の原バイトは必ず ESC を含む）。
        if b"\x1b" not in raw:
            try:
                return [raw.decode("utf-8")]
            except UnicodeDecodeError:
                pass
        try:
            return [raw.decode(_charset(payload), "replace")]
        except LookupError:
            return [raw.decode("utf-8", "replace")]
    return [text for part in payload.get("parts", []) for text in _decoded_parts(part, mime_type)]


def plain_text(payload: dict[str, Any]) -> str:
    """text/plain を優先し、無ければ text/html をテキスト化して返す。"""
    plain = _decoded_parts(payload, "text/plain")
    if any(text.strip() for text in plain):
        return "\n".join(plain)
    return "\n\n".join(html_to_text(html) for html in _decoded_parts(payload, "text/html"))


def html_body(payload: dict[str, Any]) -> str:
    return "\n".join(_decoded_parts(payload, "text/html"))


def decode_base64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def attachment_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """添付ファイルのパートを列挙する。attachmentId は取得ごとに変わるので、参照には part_id を使う。"""
    found: list[dict[str, Any]] = []

    def walk(part: dict[str, Any]) -> None:
        body = part.get("body", {})
        if part.get("filename") and (body.get("attachmentId") or body.get("data")):
            found.append(
                {
                    "part_id": part.get("partId", ""),
                    "filename": part["filename"],
                    "mime_type": part.get("mimeType", "application/octet-stream"),
                    "size": body.get("size", 0),
                }
            )
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    return found


def find_part(payload: dict[str, Any], part_id: str) -> dict[str, Any] | None:
    if payload.get("partId", "") == part_id:
        return payload
    for child in payload.get("parts", []):
        found = find_part(child, part_id)
        if found is not None:
            return found
    return None


def load_attachment_files(paths: list[str]) -> list[Attachment]:
    attachments: list[Attachment] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.is_file():
            raise ValueError(f"添付ファイルが見つかりません: {path}")
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        attachments.append((path.name, path.read_bytes(), mime_type))
    check_attachment_size(attachments)
    return attachments


def check_attachment_size(attachments: list[Attachment]) -> None:
    if sum(len(data) for _, data, _ in attachments) > MAX_ATTACHMENT_BYTES:
        raise ValueError("添付ファイルの合計が25MBを超えています。Driveのリンクで送ってください")


def build_message(
    *,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str = "",
    body: str | None = None,
    html: str | None = None,
    attachments: list[Attachment] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> EmailMessage:
    """送信用のMIMEを組み立てる。From は付けず、認証済みメールボックスにGmail側で決めさせる。"""
    message = EmailMessage()
    for name, values in (("To", to), ("Cc", cc), ("Bcc", bcc)):
        if values:
            message[name] = ", ".join(values)
    message["Subject"] = subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
    if references:
        message["References"] = references
    if body is None and html:
        body = html_to_text(html)
    message.set_content(body or "")
    if html:
        message.add_alternative(html, subtype="html")
    for filename, data, mime_type in attachments or []:
        maintype, _, subtype = mime_type.partition("/")
        message.add_attachment(
            data, maintype=maintype, subtype=subtype or "octet-stream", filename=filename
        )
    return message


def _address_list(value: str | None) -> list[str]:
    return [address for _, address in getaddresses([value or ""]) if address]


def merge_draft(
    existing: EmailMessage,
    *,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    subject: str | None = None,
    body: str | None = None,
    html: str | None = None,
    attachments: list[Attachment] | None = None,
) -> EmailMessage:
    """指定した項目だけ上書きし、残りは既存の下書きを保つ。

    本文は body / html のどちらかを渡すと両方を置き換える（片方だけなら他方は消える）。
    添付は attachments を渡したときだけ置き換え、渡さなければ既存の添付を残す。
    """
    if body is None and html is None:
        plain_part = existing.get_body(preferencelist=("plain",))
        html_part = existing.get_body(preferencelist=("html",))
        body = plain_part.get_content() if plain_part is not None else ""
        html = html_part.get_content() if html_part is not None else None
    if attachments is None:
        attachments = [
            (
                part.get_filename() or "attachment",
                part.get_payload(decode=True) or b"",
                part.get_content_type(),
            )
            for part in existing.iter_attachments()
        ]
    return build_message(
        to=to or _address_list(existing["To"]),
        cc=cc or _address_list(existing["Cc"]),
        bcc=bcc or _address_list(existing["Bcc"]),
        subject=subject if subject else str(existing["Subject"] or ""),
        body=body,
        html=html,
        attachments=attachments,
        in_reply_to=existing["In-Reply-To"],
        references=existing["References"],
    )


def parse_raw(raw: bytes) -> EmailMessage:
    return BytesParser(policy=policy.default).parsebytes(raw)  # type: ignore[return-value]


def reply_recipients(message_headers: dict[str, str], reply_all: bool, own_address: str) -> list[str]:
    own = own_address.casefold()
    primary = message_headers.get("reply-to") or message_headers.get("from")
    sent_by_me = any(
        address.casefold() == own for _, address in getaddresses([message_headers.get("from", "")])
    )
    # 自分が送ったメールへの返信は、Gmailの画面と同じく元の宛先に返す。
    values = [message_headers.get("to", "")] if sent_by_me else [primary]
    if reply_all:
        values.extend([message_headers.get("to", ""), message_headers.get("cc", "")])
    addresses = {address for _, address in getaddresses(values) if address}
    others = {address for address in addresses if address.casefold() != own}
    # 自分だけに宛てたメールへの返信なら、自分宛てのまま残す。
    return sorted(others or addresses, key=str.casefold)


def quote(message_headers: dict[str, str], text: str) -> str:
    quoted = "\n".join(f"> {line}" if line else ">" for line in text.splitlines())
    return f"{message_headers.get('date', '')} {message_headers.get('from', '')}:\n{quoted}"


def make_reply_message(
    original: dict[str, Any],
    own_address: str,
    body: str,
    reply_all: bool,
    *,
    html: str | None = None,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[Attachment] | None = None,
    include_quote: bool = False,
) -> EmailMessage:
    message_headers = headers(original)
    if include_quote:
        body = f"{body}\n\n{quote(message_headers, plain_text(original.get('payload', {})))}"
    subject = message_headers.get("subject", "")
    message_id = message_headers.get("message-id")
    return build_message(
        to=to or reply_recipients(message_headers, reply_all, own_address),
        cc=cc,
        bcc=bcc,
        subject=subject if subject.lower().startswith("re:") else f"Re: {subject}",
        body=body,
        html=html,
        attachments=attachments,
        in_reply_to=message_id,
        references=" ".join(filter(None, [message_headers.get("references", ""), message_id]))
        or None,
    )


def make_forward_message(
    original: dict[str, Any],
    *,
    to: list[str],
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    text: str = "",
    html: str | None = None,
    attachments: list[Attachment] | None = None,
) -> EmailMessage:
    message_headers = headers(original)
    subject = message_headers.get("subject", "")
    forwarded = "\n".join(
        [
            "---------- Forwarded message ---------",
            f"From: {message_headers.get('from', '')}",
            f"Date: {message_headers.get('date', '')}",
            f"Subject: {subject}",
            f"To: {message_headers.get('to', '')}",
            *([f"Cc: {message_headers['cc']}"] if message_headers.get("cc") else []),
            "",
            plain_text(original.get("payload", {})),
        ]
    )
    if html is not None:
        html = f"{html}<br><br><pre>{escape(forwarded)}</pre>"
    return build_message(
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject if subject.lower().startswith(("fwd:", "fw:")) else f"Fwd: {subject}",
        body=f"{text}\n\n{forwarded}" if text else forwarded,
        html=html,
        attachments=attachments,
    )
