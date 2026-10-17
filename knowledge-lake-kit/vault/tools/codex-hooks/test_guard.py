import subprocess
import tempfile
import unittest
from pathlib import Path

import guard


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.remote, self.repo = base / "remote.git", base / "vault"
        run("git", "init", "--bare", "-b", "main", str(self.remote), cwd=base)
        run("git", "clone", str(self.remote), str(self.repo), cwd=base)
        for k, v in (("user.name", "t"), ("user.email", "t@example.com")):
            run("git", "config", k, v, cwd=self.repo)
        (self.repo / "a.md").write_text("a\n")
        run("git", "add", "a.md", cwd=self.repo)
        run("git", "commit", "-m", "init", cwd=self.repo)
        run("git", "push", "-u", "origin", "main", cwd=self.repo)
        self.old_root = guard.ROOT
        guard.ROOT = self.repo.resolve()

    def tearDown(self):
        guard.ROOT = self.old_root
        self.tmp.cleanup()

    def decision(self, result):
        return result.get("hookSpecificOutput", {}).get("permissionDecision")

    def test_force_push_denied(self):
        r = guard.git_check("git push --force", str(self.repo))
        self.assertEqual(self.decision(r), "deny")

    def test_bulk_add_with_deletion_denied(self):
        (self.repo / "a.md").unlink()
        r = guard.git_check("git add -A", str(self.repo))
        self.assertEqual(self.decision(r), "deny")

    def test_single_add_pulls_and_allows(self):
        (self.repo / "b.md").write_text("b\n")
        r = guard.git_check("git add b.md", str(self.repo))
        self.assertIsNone(self.decision(r))

    def test_compound_add_denied(self):
        r = guard.git_check("git add a.md && git commit -m x", str(self.repo))
        self.assertEqual(self.decision(r), "deny")

    def test_public_private_reference_denied(self):
        guard.PUBLIC_AREAS = ("99_public",)
        patch = "*** Add File: 99_public/post.md\n+[x](../08_people/someone.md)\n"
        r = guard.patch_check(patch, str(self.repo))
        self.assertEqual(self.decision(r), "deny")

    def test_private_folder_reference_allowed_elsewhere(self):
        patch = "*** Add File: 02_note/x.md\n+[x](../08_people/someone.md)\n"
        self.assertEqual(guard.patch_check(patch, str(self.repo)), {})


if __name__ == "__main__":
    unittest.main()
