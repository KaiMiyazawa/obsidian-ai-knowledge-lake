from mcp.server.fastmcp import FastMCP

from gmail_unifier import server

# Claude の Gmail MCP（2026-10-01時点の30ツール）と、それを受け持つ gmail-unifier のツール。
GMAIL_MCP_COVERAGE = {
    "search_threads": "search_threads",
    "get_thread": "get_thread",
    "get_message": "read_message",
    "list_labels": "list_labels",
    "create_label": "create_label",
    "update_label": "update_label",
    "delete_label": "delete_label",
    "label_message": "modify_labels",
    "label_thread": "modify_labels",
    "unlabel_message": "modify_labels",
    "unlabel_thread": "modify_labels",
    "update_message_labels": "modify_labels",
    "trash_message": "trash",
    "trash_thread": "trash",
    "untrash_message": "untrash",
    "untrash_thread": "untrash",
    "mark_message_spam": "mark_spam",
    "mark_thread_spam": "mark_spam",
    "unmark_message_spam": "unmark_spam",
    "unmark_thread_spam": "unmark_spam",
    "apply_sensitive_message_label": "trash",
    "apply_sensitive_thread_label": "mark_spam",
    "list_drafts": "list_drafts",
    "get_draft": "get_draft",
    "create_draft": "create_draft",
    "update_draft": "update_draft",
    "delete_draft": "delete_draft",
    "send_message": "send_message",
    "reply": "send_reply",
    "forward": "forward",
}


def test_every_gmail_mcp_tool_has_a_counterpart(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('[[accounts]]\nid = "personal"\nemail = "me@example.com"\n')
    captured = {}
    monkeypatch.setattr(FastMCP, "run", lambda self, **_: captured.setdefault("mcp", self))
    server.run(config)
    names = {tool.name for tool in captured["mcp"]._tool_manager.list_tools()}
    assert len(GMAIL_MCP_COVERAGE) == 30
    missing = {tool for tool, ours in GMAIL_MCP_COVERAGE.items() if ours not in names}
    assert not missing
    assert {"send_draft", "download_attachment", "search_mail", "list_mailboxes"} <= names
