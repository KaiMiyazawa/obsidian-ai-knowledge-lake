import base64

import pytest

from gmail_unifier import handles
from gmail_unifier.gmail import (
    attachment_parts,
    build_message,
    find_part,
    label_color,
    make_forward_message,
    make_reply_message,
    merge_draft,
    parse_raw,
)


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode("ascii").rstrip("=")


ORIGINAL = {
    "id": "m1",
    "threadId": "t1",
    "payload": {
        "partId": "",
        "mimeType": "multipart/mixed",
        "headers": [
            {"name": "From", "value": "Sender <sender@example.com>"},
            {"name": "To", "value": "me@example.com"},
            {"name": "Subject", "value": "請求書"},
            {"name": "Date", "value": "Thu, 1 Oct 2026 10:00:00 +0900"},
            {"name": "Message-ID", "value": "<m1@example.com>"},
        ],
        "parts": [
            {"partId": "0", "mimeType": "text/plain", "body": {"data": _b64("本文1行目\n2行目")}},
            {
                "partId": "1",
                "mimeType": "application/pdf",
                "filename": "invoice.pdf",
                "body": {"attachmentId": "volatile-id", "size": 1234},
            },
        ],
    },
}


def test_build_message_with_html_and_japanese_attachment():
    message = build_message(
        to=["a@example.com", "b@example.com"],
        bcc=["c@example.com"],
        subject="件名",
        html="<p>こんにちは</p>",
        attachments=[("見積書.pdf", b"%PDF", "application/pdf")],
    )
    parsed = parse_raw(message.as_bytes())
    assert parsed["To"] == "a@example.com, b@example.com"
    assert parsed["Bcc"] == "c@example.com"
    assert parsed["From"] is None
    assert parsed["Subject"] == "件名"
    assert parsed.get_body(preferencelist=("plain",)).get_content().strip() == "こんにちは"
    assert "<p>こんにちは</p>" in parsed.get_body(preferencelist=("html",)).get_content()
    [attachment] = list(parsed.iter_attachments())
    assert attachment.get_filename() == "見積書.pdf"
    assert attachment.get_payload(decode=True) == b"%PDF"


def test_merge_draft_keeps_unspecified_fields_and_attachments():
    existing = parse_raw(
        build_message(
            to=["a@example.com"],
            subject="元の件名",
            body="元の本文",
            attachments=[("a.txt", b"A", "text/plain")],
            in_reply_to="<x@example.com>",
        ).as_bytes()
    )
    merged = parse_raw(merge_draft(existing, subject="新しい件名").as_bytes())
    assert merged["To"] == "a@example.com"
    assert merged["Subject"] == "新しい件名"
    assert merged["In-Reply-To"] == "<x@example.com>"
    assert merged.get_body(preferencelist=("plain",)).get_content().strip() == "元の本文"
    assert [part.get_filename() for part in merged.iter_attachments()] == ["a.txt"]


def test_merge_draft_replaces_body_and_can_drop_attachments():
    existing = parse_raw(
        build_message(
            to=["a@example.com"],
            body="古い",
            html="<p>古い</p>",
            attachments=[("a.txt", b"A", "text/plain")],
        ).as_bytes()
    )
    merged = merge_draft(existing, body="新しい", attachments=[])
    assert merged.get_body(preferencelist=("plain",)).get_content().strip() == "新しい"
    assert merged.get_body(preferencelist=("html",)) is None or (
        merged.get_body(preferencelist=("html",)).get_content_type() == "text/plain"
    )
    assert list(merged.iter_attachments()) == []


def test_reply_with_quote_overrides_and_threading_headers():
    reply = make_reply_message(
        ORIGINAL,
        "me@example.com",
        "承知しました",
        reply_all=False,
        cc=["boss@example.com"],
        include_quote=True,
    )
    text = reply.get_body(preferencelist=("plain",)).get_content()
    assert reply["To"] == "sender@example.com"
    assert reply["Cc"] == "boss@example.com"
    assert reply["Subject"] == "Re: 請求書"
    assert reply["References"] == "<m1@example.com>"
    assert "> 本文1行目" in text and "> 2行目" in text


def test_forward_includes_original_header_block_and_attachments():
    forwarded = make_forward_message(
        ORIGINAL,
        to=["dad@example.com"],
        text="確認お願いします",
        attachments=[("invoice.pdf", b"%PDF", "application/pdf")],
    )
    text = forwarded.get_body(preferencelist=("plain",)).get_content()
    assert forwarded["Subject"] == "Fwd: 請求書"
    assert forwarded["In-Reply-To"] is None
    assert text.startswith("確認お願いします")
    assert "From: Sender <sender@example.com>" in text and "本文1行目" in text
    assert [part.get_filename() for part in forwarded.iter_attachments()] == ["invoice.pdf"]


def test_attachment_parts_are_addressed_by_part_id():
    assert attachment_parts(ORIGINAL["payload"]) == [
        {"part_id": "1", "filename": "invoice.pdf", "mime_type": "application/pdf", "size": 1234}
    ]
    assert find_part(ORIGINAL["payload"], "1")["filename"] == "invoice.pdf"
    assert find_part(ORIGINAL["payload"], "9") is None


def test_label_color_presets():
    assert label_color("Red") == {"backgroundColor": "#fb4c2f", "textColor": "#ffffff"}
    with pytest.raises(ValueError):
        label_color("neon")


def test_any_handle_accepts_only_listed_kinds(monkeypatch):
    monkeypatch.setattr(handles, "_key", lambda: b"x" * 32)
    thread = handles.make_handle("thread", "personal", "t1")
    assert handles.parse_any_handle(thread, ("message", "thread"))["k"] == "thread"
    draft = handles.make_handle("draft", "personal", "d1")
    with pytest.raises(ValueError):
        handles.parse_any_handle(draft, ("message", "thread"))
