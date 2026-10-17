"""Codex lifecycle guards for an Obsidian vault. Standard library only.

- SessionStart: fetch the vault (and submodules) and report how far behind the remote it is. Never pulls.
- PreToolUse git: before a lone `git add` / `git commit`, run `git pull --rebase --autostash` and restore
  what was already staged. Refuse force push, and refuse bulk staging that includes deletions.
- PreToolUse write: refuse adding references to private folders inside public folders.
"""
import concurrent.futures
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]

# --- 保管庫に合わせて変える設定 ---------------------------------------------
# 外に出る前提のフォルダ。作らないなら () にする。
PUBLIC_AREAS = ("89_profile", "99_public")
# 公開フォルダに書いてはいけない参照（非公開フォルダのパス）。
PRIVATE_PATTERNS = re.compile(r"06_health/|08_people/|00_self/identity-private")
# ---------------------------------------------------------------------------


def submodules():
    f = ROOT / ".gitmodules"
    if not f.exists():
        return ()
    return tuple(m.strip() for m in re.findall(r"^\s*path\s*=\s*(.+)$", f.read_text(encoding="utf-8"), re.M))


def context(event, message):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}


def deny(message):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": message}}


def git(repo, *args, timeout=15):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout, check=False)


def public_path(path, cwd):
    p = Path(path).expanduser()
    p = (Path(cwd) / p if not p.is_absolute() else p).resolve()
    return any(p.is_relative_to(ROOT / area) for area in PUBLIC_AREAS)


def patch_check(patch, cwd):
    public = False
    for line in patch.splitlines():
        if line.startswith(("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: ")):
            public = public_path(line.split(": ", 1)[1], cwd)
        elif public and line.startswith("+") and PRIVATE_PATTERNS.search(line[1:]):
            return deny("vault-guard: 公開フォルダに非公開ノートへの参照を追加できない。参照を外す。")
    return {}


def git_commands(command, cwd):
    """Resolve common shell command forms without executing the shell."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = "#"
    parts, segment = [], []
    for token in lexer:
        if token and all(c in ";&|()\n" for c in token):
            if segment:
                parts.append(segment)
            segment = []
        else:
            segment.append(token)
    if segment:
        parts.append(segment)
    directory = Path(cwd)
    found = []
    for words in parts:
        if words[0] == "cd" and len(words) == 2:
            p = Path(words[1]).expanduser()
            directory = (p if p.is_absolute() else directory / p).resolve()
            continue
        while words and (words[0] in ("command", "env") or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", words[0])):
            words = words[1:]
        if not words or Path(words[0]).name != "git":
            continue
        repo_dir, i = directory, 1
        while i < len(words) and words[i].startswith("-"):
            if words[i] == "-C" and i + 1 < len(words):
                p = Path(words[i + 1]).expanduser()
                repo_dir = p if p.is_absolute() else repo_dir / p
                i += 2
            else:
                raise ValueError("Gitのグローバルオプションは-Cのみ対応。単独のgitコマンドに分ける。")
        if i < len(words):
            found.append((repo_dir.resolve(), words[i], words[i + 1:]))
    return found


def sync_repo(repo):
    staged = git(repo, "diff", "--cached", "--name-only", "-z")
    unstaged = git(repo, "diff", "--name-only", "-z")
    if staged.returncode or unstaged.returncode:
        return "ステージ状態を読み取れない。git statusで確認する。"
    paths = [p for p in staged.stdout.split("\0") if p]
    if set(paths) & set(unstaged.stdout.split("\0")):
        return "一部だけステージしたファイルがある。自動取り込みを止めた。本人と確認する。"
    remotes = git(repo, "remote")
    if remotes.returncode:
        return "リモート設定を読み取れない。"
    if not remotes.stdout.strip():
        return None
    if git(repo, "rev-parse", "--verify", "@{u}").returncode:
        return "upstreamが未設定。取り込み先を確認する。"
    pulled = git(repo, "pull", "--rebase", "--autostash", timeout=60)
    if pulled.returncode:
        return "pull --rebase --autostashが失敗した。git statusで状態を確認する。force/reset --hardは使わない。"
    if git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip():
        return "autostashの復元で競合が残った。git statusを確認して本人に相談する。"
    if paths and git(repo, "add", "-A", "--", *paths).returncode:
        return "取り込み後のステージ復元に失敗した。git statusを確認する。"
    return None


def git_check(command, cwd):
    if not re.search(r"\bgit\b[^\n]*(?:\badd\b|\bcommit\b|\bpush\b)", command):
        return {}
    try:
        calls = git_commands(command, cwd)
    except ValueError as exc:
        return deny("git-guard: " + str(exc))
    if not calls:
        return deny("git-guard: Git操作を解析できない。シェルやスクリプトで包まず単独のgitコマンドで実行する。")
    for _, verb, args in calls:
        if verb == "push" and any(a.startswith("--force") or (a.startswith("-") and not a.startswith("--") and "f" in a[1:]) or a.startswith("+") for a in args):
            return deny("git-guard: force pushは使わない。拒否されたら取り込んでから再実行する。")
    staging = [c for c in calls if c[1] in ("add", "commit")]
    if not staging:
        return {}
    if len(calls) != 1 or re.search(r"[|;]|&&|\n|\$\(|`", command):
        return deny("git-guard: add/commitは単独で実行する（workdirかgit -Cで対象を指定）。")
    directory, verb, args = staging[0]
    top = git(directory, "rev-parse", "--show-toplevel")
    if top.returncode:
        return deny("git-guard: 対象リポジトリを確認できない。")
    repo = Path(top.stdout.strip()).resolve()
    if not repo.is_relative_to(ROOT):
        return {}
    flags = args[:args.index("--")] if "--" in args else args
    all_files = (verb == "add" and any(
        a in ("-A", "--all", "-u", "--update", ".", "./", ":/", str(repo))
        or any(c in a for c in "*?[")
        or (not a.startswith("-") and (directory / a).is_dir())
        or (a.startswith("-") and not a.startswith("--") and any(c in a[1:] for c in "Au"))
        for a in args if a != "--"
    )) or (verb == "commit" and any(a == "--all" or (a.startswith("-") and not a.startswith("--") and "a" in a[1:]) for a in flags))

    def deleted():
        status = git(repo, "status", "--porcelain=v1", "-z", "--no-renames")
        if status.returncode:
            raise ValueError("git statusに失敗した。")
        return any("D" in entry[:2] for entry in status.stdout.split("\0") if entry)

    if all_files and deleted():
        return deny("git-guard: 一括ステージに削除が含まれる。git statusで確認し、意図したパスだけ個別に指定する。")
    problem = sync_repo(repo)
    if problem:
        return deny("git-guard: " + problem)
    if all_files and deleted():
        return deny("git-guard: 取り込み後の一括ステージに削除が含まれる。対象パスを個別に指定する。")
    return context("PreToolUse", "git-guard: add/commit前の取り込み確認済み。既存ステージがあれば復元済み。")


def startup():
    def fetch_status(repo):
        if not (repo / ".git").exists():
            return None
        try:
            if git(repo, "remote").stdout.strip() == "":
                return None
            if git(repo, "fetch", "--quiet", timeout=5).returncode:
                return repo.name + ": fetch失敗"
            n = git(repo, "rev-list", "--count", "HEAD..@{u}")
            return repo.name + ": " + n.stdout.strip() + "コミット遅れ" if n.returncode == 0 and n.stdout.strip() != "0" else None
        except subprocess.TimeoutExpired:
            return repo.name + ": fetch時間切れ"
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        notes = [n for n in pool.map(fetch_status, [ROOT, *(ROOT / s for s in submodules())]) if n]
    text = "vault guards: Git・公開領域のチェックが有効。起動時はfetchのみ（pullはadd/commit直前）。"
    if notes:
        text += " Git: " + " / ".join(notes)
    return context("SessionStart", text)


def handle(event):
    if event.get("hook_event_name") == "SessionStart":
        return startup()
    args = event.get("tool_input") or {}
    tool = event.get("tool_name", "")
    cwd = (args.get("workdir") if isinstance(args, dict) else None) or event.get("cwd") or str(ROOT)
    if tool in ("apply_patch", "Write", "Edit"):
        patch = args if isinstance(args, str) else args.get("command", args.get("input", ""))
        if patch:
            return patch_check(patch, cwd)
        if args.get("file_path") and public_path(args["file_path"], cwd) and PRIVATE_PATTERNS.search(args.get("content", args.get("new_string", ""))):
            return deny("vault-guard: 公開フォルダに非公開参照を書き込めない。")
        return {}
    if tool in ("Bash", "exec_command"):
        return git_check(args.get("command", args.get("cmd", "")), cwd)
    return {}


if __name__ == "__main__":
    try:
        result = handle(json.load(sys.stdin))
    except Exception as exc:
        result = deny("vault-guard: 検査に失敗した（" + type(exc).__name__ + "）。状態を確認してから再実行する。")
    print(json.dumps(result, ensure_ascii=False))
