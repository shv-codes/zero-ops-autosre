"""
Demo helper: simulate a teammate pushing to main while AutoSRE's PR is open.

The change edits the very lines AutoSRE fixed (LIMIT 50 -> LIMIT 100 in the activity
report), so the PR now has a real merge conflict for the outer loop to resolve.

Only works with the LOCAL provider: AutoSRE never pushes to main on a real GitHub repo.
To demo this on GitHub, make the same edit yourself in the GitHub web editor.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from delivery.providers import DeliveryError, LocalProvider
from workspace.gitcmd import git

FILE = "analytics/views.py"
OLD = "ORDER BY events DESC LIMIT 50"
NEW = "ORDER BY events DESC LIMIT 100"
MESSAGE = "feat(reports): show top 100 users in activity report"
TEAMMATE_DATE = "2026-10-23T09:30:00+00:00"


def push_teammate_change(provider) -> str:
    if not isinstance(provider, LocalProvider):
        raise DeliveryError("teammate simulation only runs against the local provider")
    with tempfile.TemporaryDirectory(prefix="teammate-") as tmp:
        repo = Path(tmp) / "repo"
        git("clone", "--quiet", "--branch", "main", str(provider.origin), str(repo), cwd=tmp)
        path = repo / FILE
        text = path.read_bytes().decode("utf-8")
        if OLD not in text:
            raise DeliveryError("teammate change already applied (or file changed)")
        path.write_bytes(text.replace(OLD, NEW, 1).encode("utf-8"))
        # Fixed date: on the same seeded parent this commit gets the same hash on every demo run.
        env = {"GIT_AUTHOR_NAME": "Dana Developer", "GIT_AUTHOR_EMAIL": "dana@zero-ops.dev",
               "GIT_COMMITTER_NAME": "Dana Developer", "GIT_COMMITTER_EMAIL": "dana@zero-ops.dev",
               "GIT_AUTHOR_DATE": TEAMMATE_DATE, "GIT_COMMITTER_DATE": TEAMMATE_DATE}
        git("commit", "--quiet", "-am", MESSAGE, cwd=repo, env=env)
        git("push", "--quiet", "origin", "main", cwd=repo)
        return git("rev-parse", "HEAD", cwd=repo).strip()
