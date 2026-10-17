from gmail_unifier.gmail import make_reply_message, reply_recipients


def test_reply_recipients_excludes_origin_mailbox_from_reply_all():
    result = reply_recipients(
        {"from": "Sender <sender@example.com>", "to": "univ@example.edu", "cc": "cc@example.com"},
        reply_all=True,
        own_address="univ@example.edu",
    )
    assert result == ["cc@example.com", "sender@example.com"]


def test_reply_message_leaves_from_to_the_authenticated_mailbox():
    original = {
        "threadId": "thread-1",
        "payload": {
            "headers": [
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "To", "value": "univ@example.edu"},
                {"name": "Subject", "value": "Meeting"},
                {"name": "Message-ID", "value": "<message-1@example.com>"},
            ]
        },
    }

    reply = make_reply_message(original, "univ@example.edu", "Thanks.", reply_all=False)

    assert reply["From"] is None
    assert reply["To"] == "sender@example.com"
    assert reply["Subject"] == "Re: Meeting"
    assert reply["In-Reply-To"] == "<message-1@example.com>"


def _b64(text: str, charset: str = "utf-8") -> str:
    import base64

    return base64.urlsafe_b64encode(text.encode(charset)).decode("ascii").rstrip("=")


def test_plain_text_falls_back_to_html_only_message():
    from gmail_unifier.gmail import plain_text

    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "text/html",
                "headers": [{"name": "Content-Type", "value": "text/html;charset=utf-8"}],
                "body": {"data": _b64('<style>p{}</style><p>作成完了</p><p><a href="https://example.com/x">DL</a></p>')},
            }
        ],
    }
    assert plain_text(payload) == "作成完了\n\n<https://example.com/x> DL"


def test_plain_text_prefers_plain_and_honors_charset():
    from gmail_unifier.gmail import plain_text

    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {
                "mimeType": "text/plain",
                "headers": [{"name": "Content-Type", "value": 'text/plain; charset="ISO-2022-JP"'}],
                "body": {"data": _b64("本文です", "iso-2022-jp")},
            },
            {"mimeType": "text/html", "body": {"data": _b64("<p>HTML</p>")}},
        ],
    }
    assert plain_text(payload) == "本文です"


def test_plain_text_handles_gmail_transcoded_utf8_with_legacy_charset_header():
    # Gmail API は ISO-2022-JP の本文を UTF-8 に変換して返すが、ヘッダーは元の charset のまま
    from gmail_unifier.gmail import plain_text

    payload = {
        "mimeType": "text/plain",
        "headers": [{"name": "Content-Type", "value": 'text/plain; charset="iso-2022-jp"'}],
        "body": {"data": _b64("大学の学生課です。")},
    }
    assert plain_text(payload) == "大学の学生課です。"


def test_reply_to_own_sent_message_goes_to_original_recipients():
    result = reply_recipients(
        {"from": "Me <me@example.com>", "to": "friend@example.com", "cc": "cc@example.com"},
        reply_all=False,
        own_address="me@example.com",
    )
    assert result == ["friend@example.com"]


def test_reply_to_note_to_self_stays_addressed_to_self():
    result = reply_recipients(
        {"from": "me@example.com", "to": "me@example.com"},
        reply_all=True,
        own_address="me@example.com",
    )
    assert result == ["me@example.com"]
