from gmail_unifier import handles


def test_signed_handle_round_trip(monkeypatch):
    monkeypatch.setattr(handles, "_key", lambda: b"x" * 32)
    handle = handles.make_handle("message", "univ", "message-1", "thread-1")
    assert handles.parse_handle(handle, "message") == {
        "a": "univ",
        "i": "message-1",
        "k": "message",
        "t": "thread-1",
    }


def test_handle_cannot_be_used_as_a_draft(monkeypatch):
    monkeypatch.setattr(handles, "_key", lambda: b"x" * 32)
    handle = handles.make_handle("message", "univ", "message-1")
    try:
        handles.parse_handle(handle, "draft")
    except ValueError as error:
        assert "無効" in str(error)
    else:
        raise AssertionError("message handle must not be accepted as a draft handle")
