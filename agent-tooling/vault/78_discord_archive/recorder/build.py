#!/usr/bin/env python3
""".data/raw/ に溜まった記録を、重複を除いてチャンネル別の Markdown にする（出力先 .data/export/ も Git 管理外）。

AI が読んで要点をまとめるための中間物。要点のまとめ自体は notes/ に書く。

    python3 recorder/build.py
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 生ログと中間物の置き場。先頭が「.」なので Obsidian は読み込まない（重くなるのを避ける。2026-10-10）
DATA = ROOT / ".data"
JST = timezone(timedelta(hours=9))
# 本文を持たないシステムメッセージの表示（type 18 は本文がスレッド名）
SYSTEM = {3: "通話", 6: "メッセージをピン留め", 7: "参加", 18: "スレッドを作成"}
MENTION = re.compile(r"<@!?(\d+)>")
UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]\n\r\t]+')  # Obsidian のリンクで壊れる文字も除く


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue  # 書き込み途中で切れた行


def parse_title(title: str) -> tuple[str | None, str | None]:
    """'(3) Discord | #general | サーバー名' → ('#general', 'サーバー名')。DM は ('@名前', None)。"""
    title = re.sub(r"^(\(\d+\)|•)\s*", "", title or "")  # 未読数 '(3)' と未読マーク '•'
    parts = [p.strip() for p in title.split(" | ") if p.strip()]
    if parts and parts[0] == "Discord":
        parts = parts[1:]
    if not parts:
        return None, None
    return parts[0], (parts[-1] if len(parts) > 1 else None)


def channel_info(context: dict) -> tuple[str, dict] | None:
    """画面の URL とタイトルから (channel_id, {guild_id, channel_name, guild_name}) を得る。"""
    segs = (context.get("path") or "").strip("/").split("/")
    # 読み込み途中のタイトル（'discord.com' など）は使わない
    if len(segs) < 3 or segs[0] != "channels" or " | " not in (context.get("title") or ""):
        return None
    channel_name, guild_name = parse_title(context["title"])
    return segs[2], {"guild_id": segs[1], "channel_name": channel_name, "guild_name": guild_name}


def load_channels(raw_dir: Path) -> dict[str, dict]:
    """channel_id → {guild_id, channel_name, guild_name}。最後に見た画面の情報を使う。

    context.jsonl に無いチャンネル（画面の切り替えが速く記録が間に合わなかったもの）は、
    メッセージと一緒に記録された画面の情報で補う。
    """
    channels: dict[str, dict] = {}
    path = raw_dir / "context.jsonl"
    if path.exists():
        for row in read_jsonl(path):
            found = channel_info(row)
            if found:
                channels[found[0]] = found[1]
    for msg_path in (raw_dir / "messages").glob("*.jsonl"):
        if msg_path.stem in channels:
            continue
        for row in read_jsonl(msg_path):
            found = channel_info(row.get("context") or {})
            if found and found[0] == msg_path.stem:
                channels[found[0]] = found[1]
    return channels
    for row in read_jsonl(path):
        segs = (row.get("path") or "").strip("/").split("/")
        # 読み込み途中のタイトル（'discord.com' など）は使わない
        if len(segs) < 3 or segs[0] != "channels" or " | " not in (row.get("title") or ""):
            continue
        channel_name, guild_name = parse_title(row.get("title", ""))
        channels[segs[2]] = {"guild_id": segs[1], "channel_name": channel_name, "guild_name": guild_name}
    return channels


def embed_text(e: dict) -> str:
    """埋め込み（Bot の通知カードやリンクのプレビュー）を、読める複数行テキストにする。"""
    parts = []
    if (e.get("author") or {}).get("name"):
        parts.append(f"**{e['author']['name']}**")
    title = e.get("title")
    if title:
        parts.append(f"[{title}]({e['url']})" if e.get("url") else title)
    elif e.get("url"):
        parts.append(e["url"])
    if e.get("description"):
        parts.append(e["description"])
    for f in e.get("fields") or []:
        parts.append(f"{f.get('name', '')}: {f.get('value', '')}")
    for key in ("image", "thumbnail", "video"):
        if (e.get(key) or {}).get("url"):
            parts.append(f"{key}: {e[key]['url']}")
    if (e.get("footer") or {}).get("text"):
        parts.append(f"— {e['footer']['text']}")
    return "\n".join(parts)


def normalize(row: dict) -> dict:
    m = row["message"]
    if row.get("source") == "api":
        author = m.get("author") or {}
        media = [a.get("url") for a in m.get("attachments") or [] if a.get("url")]
        embeds = [t for t in (embed_text(e) for e in m.get("embeds") or []) if t]
        reference = m.get("message_reference") or {}
        ref = reference.get("message_id") if reference.get("type", 0) == 0 else None  # type 1 は転送
        reactions = [f"{(r.get('emoji') or {}).get('name')}×{r.get('count')}" for r in m.get("reactions") or []]
        names = {u.get("id"): u.get("global_name") or u.get("username") for u in m.get("mentions") or []}
        content = MENTION.sub(lambda x: f"@{names.get(x.group(1)) or x.group(1)}", m.get("content") or "")
        extra = [f"[スタンプ: {s.get('name')}]" for s in m.get("sticker_items") or []]
        if m.get("type") in SYSTEM:
            extra.insert(0, f"_({SYSTEM[m['type']]})_")
        for snap in m.get("message_snapshots") or []:  # Discord 標準の「転送」
            fwd = snap.get("message") or {}
            media += [a.get("url") for a in fwd.get("attachments") or [] if a.get("url")]
            embeds += [t for t in (embed_text(e) for e in fwd.get("embeds") or []) if t]
            if fwd.get("content"):
                embeds.insert(0, "_(転送)_\n" + fwd["content"])
            else:
                extra.append("_(転送)_")
        content = " ".join([*extra, content]).strip()
        return {
            "id": m["id"], "timestamp": m.get("timestamp"),
            "author": author.get("global_name") or author.get("username") or "?",
            "content": content, "media": media, "embeds": embeds,
            "reply_to": ref, "reactions": reactions, "edited": bool(m.get("edited_timestamp")),
        }
    return {
        "id": m["id"], "timestamp": m.get("timestamp"), "author": m.get("author_display") or "?",
        "content": m.get("content") or "", "media": m.get("media") or [], "embeds": [],
        "reply_to": None, "reactions": [], "edited": False,
    }


def load_messages(path: Path) -> list[dict]:
    """同じメッセージが複数回記録されていたら、API 由来を優先し、その中で最後に取れたものを使う。"""
    best: dict[str, tuple[tuple, dict]] = {}
    for row in read_jsonl(path):
        m = row.get("message") or {}
        if not m.get("id"):
            continue
        rank = (row.get("source") == "api", row.get("captured_at") or "")
        if m["id"] not in best or rank >= best[m["id"]][0]:
            best[m["id"]] = (rank, normalize(row))
    return sorted((v for _, v in best.values()), key=lambda x: int(x["id"]))


def to_jst(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(JST) if ts else None
    except ValueError:
        return None


def ymd(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else "?"


def safe(name: str) -> str:
    return UNSAFE.sub("_", name).strip(" ._")[:80] or "_"


def render(title: str, messages: list[dict]) -> str:
    ids = {m["id"]: m for m in messages}
    lines = [f"# {title}", ""]
    day = None
    for m in messages:
        t = to_jst(m["timestamp"])
        if t and t.date() != day:
            day = t.date()
            lines += ["", f"## {day.isoformat()}", ""]
        head = f"- **{t.strftime('%H:%M') if t else '??:??'} {m['author']}**"
        if m["reply_to"]:
            target = ids.get(m["reply_to"])
            head += f" ↩ {target['author'] if target else '（未記録のメッセージ）'}"
        body = m["content"].replace("\n", "\n  ")
        lines.append(f"{head}: {body}" + (" _(編集済)_" if m["edited"] else ""))
        for u in m["media"]:
            lines.append(f"  - 添付: {u}")
        for e in m["embeds"]:
            lines.append("  > " + e.replace("\n", "\n  > "))
            lines.append("")
        if m["reactions"]:
            lines.append(f"  - リアクション: {' '.join(m['reactions'])}")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=DATA / "raw")
    parser.add_argument("--out-dir", type=Path, default=DATA / "export")
    args = parser.parse_args()

    channels = load_channels(args.raw_dir)
    index = defaultdict(list)
    for path in sorted((args.raw_dir / "messages").glob("*.jsonl")):
        channel_id = path.stem
        messages = load_messages(path)
        if not messages:
            continue
        info = channels.get(channel_id, {})
        guild_id = info.get("guild_id")
        if guild_id == "@me":
            group = "DM"
        elif guild_id:
            group = f"{safe(info.get('guild_name') or 'unknown')}_{guild_id}"
        else:
            group = "unknown"
        name = info.get("channel_name") or channel_id
        out = args.out_dir / group / f"{safe(name)}_{channel_id}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(f"{name}（{info.get('guild_name') or group}）", messages), encoding="utf-8")
        first, last = to_jst(messages[0]["timestamp"]), to_jst(messages[-1]["timestamp"])
        index[group].append((name, len(messages), first, last, out.relative_to(args.out_dir)))

    lines = ["# Discord 記録の一覧", "", f"生成: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}（JST）", ""]
    for group in sorted(index):
        lines += [f"## {group}", "", "| チャンネル | 件数 | 最初 | 最後 |", "| --- | --- | --- | --- |"]
        for name, n, first, last, rel in sorted(index[group], key=lambda r: r[3] or datetime.min.replace(tzinfo=JST), reverse=True):
            lines.append(f"| [{name}](<{rel.as_posix()}>) | {n} | {ymd(first)} | {ymd(last)} |")
        lines.append("")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")
    total = sum(len(v) for v in index.values())
    print(f"{total} チャンネルを書き出しました -> {args.out_dir}")


if __name__ == "__main__":
    main()
