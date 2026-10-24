"""
Workspace: a temporary clone of the target repo on its own branch.

All fixing happens here — never in the real repo or on main (FR-4.4). The coding
agent's file tools are confined to this folder (paths can't escape it, and .git is
off-limits).
"""
from __future__ import annotations

import fnmatch
import io
import os
import re
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path

from .gitcmd import GitError, git, parse_unified_diff

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", "logs", ".venv", "venv", "dist", "build"}
BOT_NAME = "AutoSRE Bot"
BOT_EMAIL = "autosre-bot@users.noreply.github.com"


class PathNotAllowed(ValueError):
    pass


class Workspace:
    def __init__(self, root: Path, base_branch: str, branch: str, base_sha: str):
        self.root = Path(root)
        self.base_branch = base_branch
        self.branch = branch
        self.base_sha = base_sha

    # -- lifecycle ---------------------------------------------------------------------
    @classmethod
    def create(cls, source: str, base_branch: str, branch: str, parent_dir: str | Path | None = None,
               git_env: dict | None = None, author: tuple[str, str] | None = None) -> "Workspace":
        parent = Path(parent_dir) if parent_dir else None
        if parent:
            parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="ws-", dir=parent))
        root = tmp / "repo"
        git("clone", "--quiet", "--branch", base_branch, source, str(root), cwd=tmp, timeout=180, env=git_env)
        name, email = author or (BOT_NAME, BOT_EMAIL)
        git("config", "user.name", name, cwd=root)
        git("config", "user.email", email, cwd=root)
        remote_branches = git("ls-remote", "--heads", "origin", branch, cwd=root, env=git_env).strip()
        if remote_branches:
            # The fix branch already exists (outer loop resuming): continue from it.
            git("fetch", "--quiet", "origin", branch, cwd=root, env=git_env)
            git("checkout", "--quiet", "-B", branch, f"origin/{branch}", cwd=root)
        else:
            git("checkout", "--quiet", "-b", branch, cwd=root)
        base_sha = git("rev-parse", f"origin/{base_branch}", cwd=root).strip()
        return cls(root, base_branch, branch, base_sha)

    def cleanup(self) -> None:
        shutil.rmtree(self.root.parent, onerror=_force_remove)

    # -- safe file access (used by the agent tools) ----------------------------------
    def resolve(self, rel: str) -> Path:
        rel = (rel or "").replace("\\", "/").strip()
        if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
            raise PathNotAllowed(f"path must be relative to the repository root: {rel!r}")
        target = (self.root / rel).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise PathNotAllowed(f"path escapes the repository: {rel!r}")
        if ".git" in Path(rel).parts:
            raise PathNotAllowed("the .git folder is off-limits")
        return target

    def read_file(self, rel: str) -> str:
        path = self.resolve(rel)
        if not path.is_file():
            raise FileNotFoundError(rel)
        return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")

    def write_file(self, rel: str, text: str) -> None:
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def exists(self, rel: str) -> bool:
        return self.resolve(rel).exists()

    def list_files(self, pattern: str = "*") -> list[str]:
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                rel = Path(dirpath, name).relative_to(self.root).as_posix()
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
                    out.append(rel)
        return sorted(out)

    def search(self, needle: str, max_hits: int = 50) -> list[dict]:
        hits = []
        for rel in self.list_files():
            try:
                text = self.read_file(rel)
            except (OSError, UnicodeDecodeError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if needle in line:
                    hits.append({"file": rel, "line": n, "text": line.strip()[:200]})
                    if len(hits) >= max_hits:
                        return hits
        return hits

    # -- git views ----------------------------------------------------------------------
    def diff(self, against: str | None = None) -> str:
        """Unified diff of the working tree (including new files) against the base."""
        untracked = git("ls-files", "--others", "--exclude-standard", "-z", cwd=self.root).split("\0")
        untracked = [p for p in untracked if p and not set(Path(p).parts) & SKIP_DIRS]
        if untracked:  # make brand-new files show up in the diff
            git("add", "--intent-to-add", "--", *untracked, cwd=self.root)
        return git("diff", "--no-color", against or self.base_sha, "--", ".", cwd=self.root)

    def changed_files(self, against: str | None = None) -> dict:
        return parse_unified_diff(self.diff(against))

    def has_uncommitted_changes(self) -> bool:
        return bool(git("status", "--porcelain", cwd=self.root).strip())

    def commit_all(self, message: str) -> str:
        git("add", "--all", cwd=self.root)
        git("commit", "--quiet", "-m", message, cwd=self.root)
        return git("rev-parse", "HEAD", cwd=self.root).strip()

    def export_tree(self, ref: str, dest: Path) -> Path:
        """Write the files of `ref` (e.g. the original base commit) into `dest`."""
        dest.mkdir(parents=True, exist_ok=True)
        import subprocess

        data = subprocess.run(["git", "archive", "--format=tar", ref], cwd=self.root,
                              capture_output=True, timeout=60, check=True).stdout
        root = dest.resolve()
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue  # directories are created as needed; links are skipped
                target = (dest / member.name).resolve()
                if not target.is_relative_to(root):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(member).read())
        return dest

    def head_sha(self) -> str:
        return git("rev-parse", "HEAD", cwd=self.root).strip()

    # -- outer loop helpers --------------------------------------------------------------
    def fetch(self, git_env: dict | None = None) -> None:
        git("fetch", "--quiet", "origin", cwd=self.root, env=git_env, timeout=120)

    def merge_base_branch(self) -> list[str]:
        """Merge the latest base branch into the fix branch. Returns conflicted files ([] if clean)."""
        result = git("merge", "--no-edit", "--no-ff", f"origin/{self.base_branch}", cwd=self.root, check=False)
        conflicted = self.conflicted_files()
        if not conflicted and "CONFLICT" in result:
            raise GitError(f"merge failed: {result.strip()}")
        return conflicted

    def conflicted_files(self) -> list[str]:
        out = git("diff", "--name-only", "--diff-filter=U", cwd=self.root)
        return [line for line in out.splitlines() if line.strip()]

    def merging(self) -> bool:
        return (self.root / ".git" / "MERGE_HEAD").exists()

    def complete_merge(self, message: str | None = None) -> str:
        git("add", "--all", cwd=self.root)
        if message:
            git("commit", "--quiet", "-m", message, cwd=self.root)
        else:
            git("commit", "--quiet", "--no-edit", cwd=self.root)
        return self.head_sha()

    def abort_merge(self) -> None:
        if self.merging():
            git("merge", "--abort", cwd=self.root, check=False)

    def reset_hard(self) -> None:
        """Throw away uncommitted edits (used when restarting a task with another brain)."""
        self.abort_merge()
        git("reset", "--quiet", "--hard", "HEAD", cwd=self.root)
        git("clean", "-fdq", cwd=self.root)

    def log_between(self, older: str, newer: str) -> str:
        return git("log", "--format=%h %an: %s", f"{older}..{newer}", cwd=self.root)


def _force_remove(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


__all__ = ["Workspace", "PathNotAllowed", "GitError"]
