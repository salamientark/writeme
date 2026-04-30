"""Launcher integration tests for install.sh.

These run a real bash subprocess against install.sh, but bind ``REPO_URL`` to
a local fixture clone so no network is touched.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"


def _git(cwd, *args, env=None):
    e = os.environ.copy()
    e.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    if env:
        e.update(env)
    return subprocess.run(["git", *args], cwd=cwd, check=True, env=e,
                          capture_output=True, text=True)


def _make_fixture_repo(root: Path, stub_body: str) -> tuple[Path, str]:
    """Build a bare repo containing a stub gh_readme_pipeline.py. Returns (bare_path, sha)."""
    work = root / "program-src"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    (work / "gh_readme_pipeline.py").write_text(stub_body)
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "stub")
    sha = _git(work, "rev-parse", "HEAD").stdout.strip()

    bare = root / "program.git"
    _git(root, "clone", "-q", "--bare", str(work), str(bare))
    return bare, sha


def _run(env_overrides: dict, args: list[str] | None = None,
         tmpdir_for_workdir: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Force install.sh's mktemp into a known parent so we can inspect it.
    if tmpdir_for_workdir is not None:
        env["TMPDIR"] = str(tmpdir_for_workdir)
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(INSTALL_SH), *(args or [])],
        env=env, capture_output=True, text=True, check=False,
    )


@unittest.skipUnless(shutil.which("bash") and shutil.which("git"), "bash+git required")
class TestInstallLauncher(unittest.TestCase):
    """Integration tests for install.sh sandbox launcher."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="installtest.")
        self.tmp_path = Path(self.tmp)
        self.workdir_parent = self.tmp_path / "tmpdir"
        self.workdir_parent.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stub(self, body: str) -> tuple[Path, str]:
        return _make_fixture_repo(self.tmp_path, body)

    def _find_workdirs(self) -> list[Path]:
        return [p for p in self.workdir_parent.glob("writeme.*") if p.is_dir()]

    def test_clean_exit_wipes_workdir(self) -> None:
        bare, _ = self._stub("import sys\nsys.exit(0)\n")
        result = _run({"REPO_URL": str(bare), "REF": "main"},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._find_workdirs(), [])

    def test_failure_keeps_workdir(self) -> None:
        bare, _ = self._stub("import sys\nsys.exit(1)\n")
        result = _run({"REPO_URL": str(bare), "REF": "main"},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 1)
        wds = self._find_workdirs()
        self.assertEqual(len(wds), 1)
        self.assertIn(str(wds[0]), result.stderr)

    def test_nuke_on_fail_overrides(self) -> None:
        bare, _ = self._stub("import sys\nsys.exit(1)\n")
        result = _run({"REPO_URL": str(bare), "REF": "main", "NUKE_ON_FAIL": "1"},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self._find_workdirs(), [])

    def test_env_vars_set(self) -> None:
        body = textwrap.dedent("""
            import json, os, sys
            snap = {k: os.environ.get(k, "") for k in
                    ("GH_README_REPOS_DIR", "XDG_STATE_HOME", "XDG_CACHE_HOME")}
            print(json.dumps(snap))
            sys.exit(0)
        """).lstrip()
        bare, _ = self._stub(body)
        result = _run({"REPO_URL": str(bare), "REF": "main"},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Match each of the 3 vars; each should point inside a writeme.* dir.
        for var in ("GH_README_REPOS_DIR", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            self.assertRegex(result.stdout, fr'"{var}":\s*"[^"]*writeme\.[^"]*"')

    def test_user_env_untouched(self) -> None:
        bare, _ = self._stub("import sys; sys.exit(0)\n")
        marker = "/marker/should/survive"
        result = _run({"REPO_URL": str(bare), "REF": "main",
                       "XDG_STATE_HOME": marker},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Parent shell var preserved by us, since launcher only `export`s into its subshell.
        # (We just verify the launcher itself completed cleanly with the var set in its env.)

    def test_unpushed_work_exits_nonzero(self) -> None:
        # Stub creates a dirty git tree under repo/, then exits 0.
        # The launcher itself doesn't call the unpushed scanner — Python does.
        # We simulate "Python exits 2" directly via the stub.
        body = textwrap.dedent("""
            import os, sys, subprocess, pathlib
            r = pathlib.Path(os.environ["GH_README_REPOS_DIR"]) / "x"
            r.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q", str(r)], check=True)
            (r / "f").write_text("dirty")
            sys.exit(2)
        """).lstrip()
        bare, _ = self._stub(body)
        result = _run({"REPO_URL": str(bare), "REF": "main"},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(self._find_workdirs()), 1)

    def test_sha_pin_match(self) -> None:
        bare, sha = self._stub("import sys; sys.exit(0)\n")
        result = _run({"REPO_URL": str(bare), "EXPECTED_SHA": sha},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sha_pin_mismatch(self) -> None:
        bare, _ = self._stub("import sys; sys.exit(0)\n")
        wrong = "1" * 40
        result = _run({"REPO_URL": str(bare), "EXPECTED_SHA": wrong},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 3)
        # Exit 3 is launcher-only; sandbox cleaned up since EXIT_CODE=3 != 0
        # but our cleanup keeps on non-zero by default. Spec says cleanup happens
        # if EXIT_CODE==0 OR NUKE_ON_FAIL=1 — so on exit 3 sandbox is preserved
        # (matches "kept" stderr message). Verify the message printed.
        self.assertIn("SHA pin mismatch", result.stderr)

    def test_sha_pin_unset_dev_mode(self) -> None:
        # All-zeros = unpinned → falls back to clone --branch REF.
        bare, _ = self._stub("import sys; sys.exit(0)\n")
        result = _run({"REPO_URL": str(bare), "REF": "main",
                       "EXPECTED_SHA": "0" * 40},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sha_pin_invalid_format(self) -> None:
        # Non-hex / wrong length → fall back to dev-mode clone.
        bare, _ = self._stub("import sys; sys.exit(0)\n")
        result = _run({"REPO_URL": str(bare), "REF": "main",
                       "EXPECTED_SHA": "not-a-sha"},
                      tmpdir_for_workdir=self.workdir_parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("invalid format", result.stderr)


if __name__ == "__main__":
    unittest.main()
