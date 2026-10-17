import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

spec = importlib.util.spec_from_file_location("guard", Path(__file__).with_name("guard.py"))
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def blocked(result):
    return result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


class Guards(unittest.TestCase):
    def test_public_patch(self):
        self.assertTrue(blocked(guard.patch_check("*** Add File: 99_public/a.md\n+[[08_people/a]]", guard.ROOT)))
        self.assertFalse(blocked(guard.patch_check("*** Update File: 99_public/a.md\n-06_health/a\n+public", guard.ROOT)))
        self.assertFalse(blocked(guard.patch_check("*** Add File: 02_note/a.md\n+08_people/a", guard.ROOT)))
        self.assertTrue(blocked(guard.patch_check("*** Update File: a.md\n*** Move to: 89_profile/a.md\n+relationship-end", guard.ROOT)))

    def test_apply_patch_string_input(self):
        self.assertTrue(blocked(guard.handle({"tool_name": "apply_patch", "tool_input": "*** Add File: 99_public/a.md\n+06_health/a"})))

    def test_calendar(self):
        tool = "mcp__codex_apps__google_calendar_create_event"
        self.assertTrue(blocked(guard.calendar_check(tool, {"color_id": "7"}, {})))
        self.assertTrue(blocked(guard.calendar_check(tool, {"color_id": "9", "start_date": "2026-10-07", "end_date": "2026-10-07"}, {})))
        self.assertFalse(blocked(guard.calendar_check(tool, {"color_id": "9", "start_date": "2026-10-07", "end_date": "2026-10-08"}, {})))
        self.assertTrue(blocked(guard.calendar_check("mcp__claude_ai_Google_Calendar__create_event", {"allDay": True, "startTime": "2026-10-07T00:00:00+09:00", "colorId": "9"}, {})))
        event = {"session_id": str(uuid.uuid4())}
        args = {"title": "fixture"}
        self.assertTrue(blocked(guard.calendar_check(tool, args, event)))
        self.assertFalse(blocked(guard.calendar_check(tool, args, event)))
        self.assertTrue(blocked(guard.calendar_check(tool, {"title": "changed"}, event)))

    def test_mail_attachments(self):
        tool = "mcp__gmail_unifier__send_message"
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "attachment"
            self.assertTrue(blocked(guard.send_check(tool, {"attachment_paths": [str(file)]}, tmp)))
            with file.open("wb") as f:
                f.truncate(26 * 1024 * 1024)
            self.assertTrue(blocked(guard.send_check(tool, {"attachment_paths": [str(file)]}, tmp)))
            with file.open("wb") as f:
                f.truncate(3 * 1024 * 1024)
            result = guard.send_check(tool, {"attachment_paths": ["attachment"]}, tmp)
            self.assertIn("2MB超", result["hookSpecificOutput"]["additionalContext"])

    def test_git_force(self):
        for command in ("git push --force", "git -C '/tmp/a b' push -uf origin HEAD", "git push origin +HEAD:main", "git push --force-with-lease"):
            self.assertTrue(blocked(guard.git_check(command, guard.ROOT)), command)
        self.assertFalse(blocked(guard.git_check("git push origin HEAD", guard.ROOT)))
        self.assertTrue(blocked(guard.git_check("git add a && git commit -m x", guard.ROOT)))

    def test_parser(self):
        self.assertEqual(guard.git_commands("git -C 'a b' add -- file", "/tmp"), [(Path("/tmp/a b").resolve(), "add", ["--", "file"])])
        self.assertEqual(guard.git_commands("cd 'a b' && git status", "/tmp")[0][0], Path("/tmp/a b").resolve())

    def test_json_protocol(self):
        completed = subprocess.run(["python3", str(Path(guard.__file__))], input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git push --force"}}), text=True, capture_output=True, check=True)
        self.assertTrue(blocked(json.loads(completed.stdout)))


class GitIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.remote = self.root / "remote.git"
        self.repo = self.root / "vault"
        self.other = self.root / "other"
        self.run_git(self.root, "init", "--bare", str(self.remote))
        self.run_git(self.root, "clone", str(self.remote), str(self.repo))
        self.configure(self.repo)
        (self.repo / "a").write_text("initial\n")
        self.run_git(self.repo, "add", "a")
        self.run_git(self.repo, "commit", "-m", "initial")
        self.run_git(self.repo, "push", "-u", "origin", "HEAD")
        self.run_git(self.root, "clone", str(self.remote), str(self.other))
        self.configure(self.other)

    def tearDown(self):
        self.tmp.cleanup()

    def run_git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout

    def configure(self, repo):
        self.run_git(repo, "config", "user.email", "fixture@example.invalid")
        self.run_git(repo, "config", "user.name", "Fixture")

    def advance_remote(self):
        (self.other / "b").write_text("remote\n")
        self.run_git(self.other, "add", "b")
        self.run_git(self.other, "commit", "-m", "remote")
        self.run_git(self.other, "push")

    def test_pull_and_restore_staging(self):
        self.advance_remote()
        (self.repo / "a").write_text("local\n")
        self.run_git(self.repo, "add", "a")
        with patch.object(guard, "ROOT", self.repo):
            self.assertFalse(blocked(guard.git_check("git commit -m fixture", self.repo)))
        self.assertTrue((self.repo / "b").exists())
        self.assertEqual(self.run_git(self.repo, "diff", "--cached", "--name-only").strip(), "a")
        self.assertEqual((self.repo / "a").read_text(), "local\n")

    def test_partial_stage_is_preserved(self):
        (self.repo / "a").write_text("staged\n")
        self.run_git(self.repo, "add", "a")
        (self.repo / "a").write_text("unstaged\n")
        before = self.run_git(self.repo, "diff", "--cached")
        with patch.object(guard, "ROOT", self.repo):
            self.assertTrue(blocked(guard.git_check("git add a", self.repo)))
        self.assertEqual(self.run_git(self.repo, "diff", "--cached"), before)

    def test_deleted_bulk_vs_explicit(self):
        (self.repo / "a").unlink()
        with patch.object(guard, "ROOT", self.repo):
            for command in ("git add -A", "git add .", "git commit -am fixture"):
                self.assertTrue(blocked(guard.git_check(command, self.repo)))
            self.assertFalse(blocked(guard.git_check("git add -- a", self.repo)))

    def test_pull_failure_blocks_staging(self):
        self.run_git(self.repo, "remote", "set-url", "origin", str(self.root / "missing"))
        with patch.object(guard, "ROOT", self.repo):
            self.assertTrue(blocked(guard.git_check("git add a", self.repo)))

    def test_autostash_conflict_is_not_restaged(self):
        (self.other / "a").write_text("remote change\n")
        self.run_git(self.other, "add", "a")
        self.run_git(self.other, "commit", "-m", "remote change")
        self.run_git(self.other, "push")
        (self.repo / "a").write_text("local change\n")
        self.run_git(self.repo, "add", "a")
        with patch.object(guard, "ROOT", self.repo):
            self.assertTrue(blocked(guard.git_check("git commit -m fixture", self.repo)))
        self.assertEqual(self.run_git(self.repo, "diff", "--name-only", "--diff-filter=U").strip(), "a")

    def test_staged_gitlink_deletion_blocks_bulk(self):
        head = self.run_git(self.repo, "rev-parse", "HEAD").strip()
        self.run_git(self.repo, "update-index", "--add", "--cacheinfo", "160000," + head + ",submodule")
        self.run_git(self.repo, "commit", "-m", "gitlink")
        self.run_git(self.repo, "rm", "--cached", "submodule")
        with patch.object(guard, "ROOT", self.repo):
            self.assertTrue(blocked(guard.git_check("git add -A", self.repo)))


if __name__ == "__main__":
    unittest.main()
