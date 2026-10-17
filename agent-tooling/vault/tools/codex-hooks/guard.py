"""Codex lifecycle guards. Standard library only; no mail/calendar writes."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_REF = re.compile(r"08_people/|06_health/|relationship-end")
SUBMODULES = ("01_diary", "89_profile/github-profile", "99_public")
RULES = "02_note/calendar-color-rules.md: 11=重要(月5件まで)、6=準重要、1=仮、9=学び、10=仕事、3=私用、4=健康、8=生活の繰り返し、5=目印。7は使わない。色なしは雑多な用事のみ。"


def context(event, message):
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": message}}


def deny(message):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": message}}


def git(repo, *args, timeout=15):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout, check=False)


def public_path(path, cwd):
    p = Path(path).expanduser()
    p = (Path(cwd) / p if not p.is_absolute() else p).resolve()
    return any(p.is_relative_to(ROOT / area) for area in ("99_public", "89_profile"))


def patch_check(patch, cwd):
    public = False
    for line in patch.splitlines():
        if line.startswith(("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: ")):
            public = public_path(line.split(": ", 1)[1], cwd)
        elif public and line.startswith("+") and PRIVATE_REF.search(line[1:]):
            return deny("vault-guard: 公開領域へ非公開ノートへの参照を追加できない。08_people/・06_health/・relationship-endへの参照を外す。")
    return {}


def calendar_check(tool, args, event):
    if not re.search(r"calendar.*(?:create_event|update_event)$", tool, re.I):
        return {}
    color = args.get("color_id", args.get("colorId"))
    if str(color) == "7":
        return deny("vault-guard: ピーコック(7)は使わない。" + RULES)
    if args.get("allDay") is True:
        if any(t and not str(t).endswith("Z") for t in (args.get("startTime"), args.get("endTime"))):
            return deny("vault-guard: allDayの日時はZで渡す。+09:00では日付がずれる。終了日は最終日の翌日。")
    # Codex connector uses date-only all-day boundaries, unlike the Claude connector.
    dates = (args.get("start_date"), args.get("end_date"))
    if any(dates):
        if any(d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)) for d in dates):
            return deny("vault-guard: 終日はstart_date/end_dateをYYYY-MM-DDで渡す。")
        if args.get("start_time") or args.get("end_time"):
            return deny("vault-guard: 終日の日付と時刻を混在させない。")
        if all(dates) and dates[1] <= dates[0]:
            return deny("vault-guard: 終日の終了日は最終日の翌日（開始日より後）。")
    if tool.endswith("create_event") and color is None:
        # One reminder per exact call and session; state contains hashes only.
        key = hashlib.sha256(json.dumps([event.get("session_id", "unknown"), tool, args], sort_keys=True).encode()).hexdigest()
        state = Path(tempfile.gettempdir()) / ("codex-vault-uncolored-" + str(os.getuid()))
        state.mkdir(mode=0o700, exist_ok=True)
        try:
            fd = os.open(state / key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return {}
        os.close(fd)
        return deny("vault-guard: 色が未指定。" + RULES + " 雑多な用事で色なしなら、同じ引数で再実行すれば通る。")
    return {}


def send_check(tool, args, cwd):
    if not re.search(r"mcp__gmail[-_]unifier__(send_message|send_reply|forward|send_draft)$", tool):
        return {}
    total = 0
    for name in args.get("attachment_paths") or []:
        path = Path(name).expanduser()
        if not path.is_absolute():
            path = Path(cwd) / path
        if not path.is_file():
            return deny("send-check: 添付ファイルが見つからない。送信前にattachment_pathsを確認する。")
        total += path.stat().st_size
    if total > 25 * 1024 * 1024:
        return deny("send-check: 添付合計が25MBを超える。圧縮か分割が必要。")
    text = "send-check: 宛先・件名・本文・添付を本人に提示し、明示的な送信許可を得る。返信・転送は元メール、send_draftは下書きを読み、実際の宛先と内容を確認する。"
    if total > 2 * 1024 * 1024:
        text += " 添付が2MB超。自治体・学校・小さな組織あては2MB以下が目安。"
    return context("PreToolUse", text)


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
                # -c, --git-dir and other global options can change repository semantics.
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
        return "一部だけステージしたファイルがある。autostash後の復元で未ステージ分を混ぜるため、自動取り込みを止めた。本人と確認する。"
    remotes = git(repo, "remote")
    if remotes.returncode:
        return "リモート設定を読み取れない。"
    if not remotes.stdout.strip():
        return None
    if git(repo, "rev-parse", "--verify", "@{u}").returncode:
        return "upstreamが未設定。取り込み先を確認する。"
    # Exact AGENTS.md command, before staging. Restore only already-staged paths.
    pulled = git(repo, "pull", "--rebase", "--autostash", timeout=60)
    if pulled.returncode:
        return "pull --rebase --autostashが失敗した。git statusで状態を確認する。force/reset --hardは使わない。"
    # autostash can report success yet leave conflicts; do not restage those.
    if git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip():
        return "autostashの復元で競合が残った。git statusを確認して本人に相談する。"
    if paths and git(repo, "add", "-A", "--", *paths).returncode:
        return "取り込み後のステージ復元に失敗した。git statusを確認する。"
    return None


def git_check(command, cwd):
    relevant = re.search(r"\bgit\b[^\n]*(?:\badd\b|\bcommit\b|\bpush\b)", command)
    if not relevant:
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
    staging = [(directory, verb, args) for directory, verb, args in calls if verb in ("add", "commit")]
    if not staging:
        return {}
    # Staging pipelines/compound commands can change state before the guarded operation.
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
    all_files = (verb == "add" and any(a in ("-A", "--all", "-u", "--update", ".", "./", ":/", str(repo)) or any(c in a for c in "*?[") or (not a.startswith("-") and (directory / a).is_dir()) or (a.startswith("-") and not a.startswith("--") and any(c in a[1:] for c in "Au")) for a in args if a != "--")) or (verb == "commit" and any(a == "--all" or (a.startswith("-") and not a.startswith("--") and "a" in a[1:]) for a in flags))
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
        if not repo.exists():
            return None
        try:
            fetched = git(repo, "fetch", "--quiet", timeout=5)
            if fetched.returncode:
                return repo.name + ": fetch失敗"
            n = git(repo, "rev-list", "--count", "HEAD..@{u}")
            return repo.name + ": " + n.stdout.strip() + "コミット遅れ" if n.returncode == 0 and n.stdout.strip() != "0" else None
        except subprocess.TimeoutExpired:
            return repo.name + ": fetch時間切れ"
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        notes = [n for n in pool.map(fetch_status, [ROOT, *(ROOT / s for s in SUBMODULES)]) if n]
    text = "Codex guards: 公開参照・カレンダー色・Git・メール添付のチェックが有効。送信承認はチャットと通常の承認を使う。起動時はfetchのみ。"
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
        if args.get("file_path") and public_path(args["file_path"], cwd) and PRIVATE_REF.search(args.get("content", args.get("new_string", ""))):
            return deny("vault-guard: 公開領域に非公開参照を書き込めない。")
    if tool in ("Bash", "exec_command"):
        return git_check(args.get("command", args.get("cmd", "")), cwd)
    return calendar_check(tool, args, event) or send_check(tool, args, cwd)


if __name__ == "__main__":
    try:
        result = handle(json.load(sys.stdin))
    except Exception as exc:
        # Supported denial, rather than a hook error that Codex may fail open on.
        result = deny("codex-guard: 検査に失敗した（" + type(exc).__name__ + "）。状態を確認してから再実行する。")
    print(json.dumps(result, ensure_ascii=False))
