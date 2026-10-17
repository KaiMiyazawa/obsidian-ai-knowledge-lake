#!/usr/bin/env python3
"""Discord Passive Recorder の受信サーバー。

拡張機能から POST された記録を、チャンネルごとの JSONL として .data/raw/ に追記する（Git 管理外）。
127.0.0.1 でしか待ち受けない。標準ライブラリのみ。

    python3 recorder/receiver.py            # 既定: 127.0.0.1:8765、保存先 ../.data/raw
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parent.parent
MAX_BODY = 50 * 1024 * 1024
SNOWFLAKE = re.compile(r"^\d{5,25}$")
_lock = Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def completed(raw_dir: Path) -> list[str]:
    """最古まで取り終えたチャンネルの ID 一覧（巡回の「取得済みは飛ばす」が使う）。"""
    path = raw_dir / "complete.jsonl"
    if not path.exists():
        return []
    ids = set()
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                ids.add(json.loads(line)["channel_id"])
            except (ValueError, KeyError):
                continue
    return sorted(ids)


def oldest_known(raw_dir: Path) -> dict[str, str]:
    """チャンネルごとに、記録済みの一番古いメッセージ ID（巡回はここへ飛んでから遡る。持っている分を読み直さないため）。"""
    oldest: dict[str, str] = {}
    for path in (raw_dir / "messages").glob("*.jsonl"):
        best = None
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    mid = json.loads(line)["message"]["id"]
                except (ValueError, KeyError, TypeError):
                    continue
                if best is None or int(mid) < int(best):
                    best = mid
        if best:
            oldest[path.stem] = best
    return oldest


def store(raw_dir: Path, items: list[dict]) -> int:
    """items を .data/raw/ に書き込み、保存したメッセージ数を返す。"""
    saved = 0
    by_channel: dict[str, list[dict]] = {}
    contexts: list[dict] = []
    completes: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        captured_at = item.get("captured_at") or now()
        context = item.get("context") if isinstance(item.get("context"), dict) else {}
        if item.get("kind") == "context":
            contexts.append({"captured_at": captured_at, **context})
        elif item.get("kind") == "complete":
            # チャンネルの先頭（「#〇〇へようこそ！」）まで表示された = 最古まで取り終えた
            channel_id = str(item.get("channel_id", ""))
            if SNOWFLAKE.match(channel_id):
                completes.append({"captured_at": captured_at, "channel_id": channel_id,
                                  "via": item.get("via"), "context": context})
        elif item.get("kind") == "messages":
            for message in item.get("messages") or []:
                channel_id = str(message.get("channel_id", "")) if isinstance(message, dict) else ""
                if not SNOWFLAKE.match(channel_id):
                    continue
                by_channel.setdefault(channel_id, []).append({
                    "captured_at": captured_at,
                    "source": item.get("source"),
                    "context": context,
                    "message": message,
                })
                saved += 1
    with _lock:
        if contexts:
            append(raw_dir / "context.jsonl", contexts)
        if completes:
            append(raw_dir / "complete.jsonl", completes)
        for channel_id, rows in by_channel.items():
            append(raw_dir / "messages" / f"{channel_id}.jsonl", rows)
    return saved


class Handler(BaseHTTPRequestHandler):
    raw_dir: Path

    def _reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._reply(200, {"ok": True})
        elif self.path == "/completed":
            # 拡張機能の GET には Chrome が Origin を付けない（2026-09-30 に 403 で止まった）ので、専用ヘッダーで判定する。
            # Web ページがこのヘッダーを付けるとブラウザが事前確認（OPTIONS）を挟み、ここは応じないので読まれない
            origin = self.headers.get("Origin", "")
            if self.headers.get("X-Discord-Recorder") != "1" or origin.startswith(("http://", "https://")):
                self._reply(403, {"error": "forbidden"})
                return
            self._reply(200, {"channels": completed(self.raw_dir), "oldest": oldest_known(self.raw_dir)})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        # 拡張機能（chrome-extension://）以外の Web ページからの書き込みを拒否する
        origin = self.headers.get("Origin", "")
        if self.path != "/ingest" or self.headers.get("X-Discord-Recorder") != "1" \
                or not origin.startswith("chrome-extension://"):
            self._reply(403, {"error": "forbidden"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._reply(413, {"error": "bad length"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
            saved = store(self.raw_dir, payload.get("items") or [])
        except (ValueError, AttributeError) as e:
            self._reply(400, {"error": str(e)})
            return
        self._reply(200, {"ok": True, "saved": saved})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"{now()} {self.address_string()} {fmt % args}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--raw-dir", type=Path, default=ROOT / ".data" / "raw")
    args = parser.parse_args()
    Handler.raw_dir = args.raw_dir
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"listening on http://127.0.0.1:{args.port} -> {args.raw_dir}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
