#!/usr/bin/env python3
""".data/raw/ を集計し、ナレッジ抽出の下準備を .data/export/_analysis/ に書き出す（Git 管理外）。

- inventory.md … サーバー（DM はまとめて1行）ごとの期間・件数・自分の発言数・発言者数・よく動くチャンネル
- links/<group>.md … 共有された URL の上位（Discord の CDN と GIF は除く）。回数と初出
- self/<group>.md … 自分の発言だけを時系列で（前後関係が分かるよう返信先も付ける）

    python3 recorder/analyze.py [--me YOUR_DISCORD_USER_ID]
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

from build import DATA, load_channels, load_messages, read_jsonl, safe, to_jst, ymd

URL = re.compile(r"https?://[^\s<>()\]\"'`|]+")
LINK_LIMIT = 300  # サーバーごとに残す URL の数（全部だと数十 MB になる）
SKIP_HOSTS = ("cdn.discordapp.com", "media.discordapp.net", "tenor.com", "giphy.com", "images-ext-")


def author_ids(path: Path) -> dict[str, str]:
    """message id → author id（build.normalize は表示名しか残さないので別に読む）。"""
    out = {}
    for row in read_jsonl(path):
        m = row.get("message") or {}
        aid = (m.get("author") or {}).get("id")
        if m.get("id") and aid:
            out[m["id"]] = aid
    return out


def urls_of(m: dict) -> list[str]:
    found = URL.findall(m["content"])
    for e in m["embeds"]:
        found += URL.findall(e)
    return [u.rstrip(".,、。)>") for u in found if not any(h in u for h in SKIP_HOSTS)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=DATA / "raw")
    parser.add_argument("--out-dir", type=Path, default=DATA / "export" / "_analysis")
    parser.add_argument("--me", default="YOUR_DISCORD_USER_ID", help="自分の Discord ユーザー ID")
    args = parser.parse_args()

    channels = load_channels(args.raw_dir)
    stats: dict[str, dict] = defaultdict(lambda: {
        "channels": Counter(), "n": 0, "mine": 0, "authors": set(), "first": None, "last": None})
    links: dict[str, dict[str, list]] = defaultdict(dict)  # group → url → [count, first, channel]
    mine: dict[str, list] = defaultdict(list)

    for path in sorted((args.raw_dir / "messages").glob("*.jsonl")):
        messages = load_messages(path)
        if not messages:
            continue
        info = channels.get(path.stem, {})
        gid = info.get("guild_id")
        group = "DM" if gid == "@me" else (info.get("guild_name") or "unknown") if gid else "unknown"
        cname = info.get("channel_name") or path.stem
        ids = author_ids(path)
        byid = {m["id"]: m for m in messages}
        s = stats[group]
        s["channels"][cname] += len(messages)
        s["n"] += len(messages)
        for m in messages:
            t = to_jst(m["timestamp"])
            if t:
                s["first"] = min(s["first"] or t, t)
                s["last"] = max(s["last"] or t, t)
            s["authors"].add(ids.get(m["id"], m["author"]))
            for u in urls_of(m):
                rec = links[group].setdefault(u, [0, t, cname])
                rec[0] += 1
            if ids.get(m["id"]) == args.me:
                s["mine"] += 1
                ref = byid.get(m["reply_to"]) if m["reply_to"] else None
                mine[group].append((t, cname, m, ref))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = sorted(stats.items(), key=lambda kv: -kv[1]["n"])
    lines = ["| サーバー | 件数 | 自分 | 発言者 | チャンネル | 最初 | 最後 | 多いチャンネル |", "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |"]
    for g, s in rows:
        top = "、".join(f"{c}({n})" for c, n in s["channels"].most_common(3))
        lines.append(f"| {g} | {s['n']} | {s['mine']} | {len(s['authors'])} | {len(s['channels'])} | {ymd(s['first'])} | {ymd(s['last'])} | {top} |")
    (args.out_dir / "inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    (args.out_dir / "links").mkdir(exist_ok=True)
    for g, _ in rows:
        if not links[g]:
            continue
        hosts = Counter(re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", u) for u in links[g])
        ranked = sorted(links[g].items(), key=lambda kv: (-kv[1][0], str(kv[1][1])))
        out = [f"# 共有されたリンク — {g}", "", f"URL {len(ranked)} 件のうち、共有回数の多い上位 {min(len(ranked), LINK_LIMIT)} 件。", "",
               "多いドメイン: " + "、".join(f"{h}({n})" for h, n in hosts.most_common(15)), ""]
        out += [f"- {ymd(t)} {c} ×{n} {u}" for u, (n, t, c) in ranked[:LINK_LIMIT]]
        (args.out_dir / "links" / f"{safe(g)}.md").write_text("\n".join(out) + "\n", encoding="utf-8")

    (args.out_dir / "self").mkdir(exist_ok=True)
    for g, items in mine.items():
        body = [f"# 自分の発言 — {g}", ""]
        for t, c, m, ref in sorted(items, key=lambda x: x[0] or to_jst("1970-01-01T00:00:00+00:00")):
            head = f"- {t.strftime('%Y-%m-%d %H:%M') if t else '?'} {c}"
            if ref:
                head += f" ↩ {ref['author']}「{ref['content'][:80]}」"
            body.append(f"{head}: {m['content']}".replace("\n", "\n  "))
            body += [f"  - 添付: {u}" for u in m["media"]]
        (args.out_dir / "self" / f"{safe(g)}.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    print(f"{len(rows)} グループを集計しました -> {args.out_dir}")


if __name__ == "__main__":
    main()
