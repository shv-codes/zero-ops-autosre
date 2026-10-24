#!/usr/bin/env python3
"""
Build the victim service's git history (Windows/macOS/Linux).

The files in ./victim_service are the *current* state of the app (with the leak).
This script replays how that code "grew" as five commits by four people, so that
AutoSRE has a real history to investigate:

    1. Alice    bootstrap project + health endpoint
    2. Bob      reporting connection pool + top-pages report   (correct pool usage)
    3. Dana     metrics summary endpoint (ORM)
    4. Charlie  user-activity report   <-- forgets to return the pool connection (the leak)
    5. Dana     README + load-test script

It creates:
    var/victim_origin.git   a bare repo playing the role of "GitHub" (the remote)
    var/victim_repo         a normal clone of it (what AutoSRE reads history from)

Usage:  python scripts/seed_victim_repo.py [--force]
"""
from __future__ import annotations

import argparse
import ast
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "victim_service"
DEFAULT_VAR = ROOT / "var"
SEED_ANCHOR = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

IGNORED_PARTS = {"__pycache__", "logs", ".pytest_cache"}
IGNORED_NAMES = {"db.sqlite3"}

PEOPLE = {
    "alice": ("Alice Architect", "alice@zero-ops.dev"),
    "bob": ("Bob Builder", "bob@zero-ops.dev"),
    "dana": ("Dana Developer", "dana@zero-ops.dev"),
    "charlie": ("Charlie Contributor", "charlie@zero-ops.dev"),
}

# Which view functions / url names exist after each commit.
VIEWS_BY_STAGE = {
    1: ["health"],
    2: ["health", "top_pages"],
    3: ["health", "top_pages", "metrics_summary"],
    4: ["health", "top_pages", "metrics_summary", "user_activity_report"],
}

URL_LINES = {
    "health": '    path("health/", views.health, name="health"),',
    "top_pages": '    path("reports/top-pages/", views.top_pages, name="top_pages"),',
    "metrics_summary": '    path("metrics/summary/", views.metrics_summary, name="metrics_summary"),',
    "user_activity_report": '    path("reports/user-activity/", views.user_activity_report, name="user_activity_report"),',
}

COMMITS = [
    # (who, days_ago, message, files copied verbatim from ./victim_service, stage for views/urls)
    ("alice", 9, "feat: bootstrap victim service with health endpoint", [
        ".autosre.yml", ".gitignore", "Dockerfile", "manage.py", "pytest.ini", "requirements.txt",
        "victim_project/__init__.py", "victim_project/settings.py", "victim_project/urls.py",
        "victim_project/wsgi.py", "analytics/__init__.py", "analytics/apps.py", "analytics/models.py",
        "analytics/observability.py", "analytics/migrations/__init__.py",
        "analytics/migrations/0001_initial.py", "analytics/management/__init__.py",
        "analytics/management/commands/__init__.py", "analytics/management/commands/seed_activity.py",
        "tests/__init__.py", "tests/test_health.py",
    ], 1),
    ("bob", 6, "feat(reports): add pooled raw-SQL reporting with top-pages report", [
        "analytics/pool.py", "conftest.py", "tests/fakes.py", "tests/test_reports.py",
    ], 2),
    ("dana", 4, "feat(metrics): add metrics summary endpoint", ["tests/test_metrics.py"], 3),
    ("charlie", 2, "perf(reports): add fast raw-SQL user activity report", [], 4),
    ("dana", 1, "docs: add service README and load-test script", ["README.md", "traffic_simulator.py"], 4),
]


def read_lf(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def write_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def views_for_stage(stage: int) -> str:
    """Rebuild analytics/views.py as it looked after `stage` from the current file."""
    source = read_lf(SOURCE / "analytics/views.py")
    tree = ast.parse(source)
    lines = source.split("\n")
    funcs = {
        node.name: "\n".join(lines[node.lineno - 1: node.end_lineno])
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    wanted = VIEWS_BY_STAGE[stage]
    local_imports = []
    if stage >= 3:
        local_imports.append("from .models import UserActivity")
    if stage >= 2:
        local_imports.append("from .pool import report_pool")
    header = "from django.http import JsonResponse\n"
    if local_imports:
        header += "\n" + "\n".join(local_imports) + "\n"
    return header + "\n\n" + "\n\n\n".join(funcs[name] for name in wanted) + "\n"


def urls_for_stage(stage: int) -> str:
    entries = "\n".join(URL_LINES[name] for name in VIEWS_BY_STAGE[stage])
    return (
        "from django.urls import path\n\nfrom . import views\n\n"
        f"urlpatterns = [\n{entries}\n]\n"
    )


def git(*args: str, cwd: Path, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **(env or {})},
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def _force_remove(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)  # git objects are read-only on Windows
    func(path)


def rmtree(path: Path) -> None:
    """Delete a folder. If Windows keeps the folder itself locked (e.g. a terminal is
    open inside it), empty it instead — git can clone into an empty folder."""
    if not path.exists():
        return
    try:
        shutil.rmtree(path, onerror=_force_remove)
    except PermissionError:
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child, onerror=_force_remove)
            else:
                os.chmod(child, stat.S_IWRITE)
                child.unlink()


def source_files() -> set[str]:
    files = set()
    for path in SOURCE.rglob("*"):
        rel = path.relative_to(SOURCE)
        if path.is_file() and not (set(rel.parts) & IGNORED_PARTS) and path.name not in IGNORED_NAMES \
                and path.suffix != ".pyc":
            files.add(rel.as_posix())
    return files


def seed(var: Path = DEFAULT_VAR, force: bool = False) -> tuple[Path, Path]:
    """Create <var>/victim_origin.git and <var>/victim_repo. Returns (origin, clone)."""
    origin, clone, build = var / "victim_origin.git", var / "victim_repo", var / "_seed_build"
    if origin.exists() or clone.exists():
        if not force:
            raise SystemExit(f"{origin} or {clone} already exists. Re-run with --force to recreate.")
        rmtree(origin)
        rmtree(clone)
    rmtree(build)

    # Sanity check: the last stage must reproduce the current files exactly.
    assert views_for_stage(4) == read_lf(SOURCE / "analytics/views.py"), "views.py stages out of sync"
    assert urls_for_stage(4) == read_lf(SOURCE / "analytics/urls.py"), "urls.py stages out of sync"
    covered = {f for c in COMMITS for f in c[3]} | {"analytics/views.py", "analytics/urls.py"}
    missing = source_files() - covered
    assert not missing, f"files not assigned to any commit: {sorted(missing)}"

    build.mkdir(parents=True)
    git("init", "-q", "-b", "main", cwd=build)
    git("config", "core.autocrlf", "false", cwd=build)

    # Fixed anchor date: identical content + authors + dates = identical commit hashes on every
    # re-seed, so the demo always shows the same suspect commit (e.g. Charlie's leak) to judges.
    now = SEED_ANCHOR
    for who, days_ago, message, files, stage in COMMITS:
        for rel in files:
            write_lf(build / rel, read_lf(SOURCE / rel))
        write_lf(build / "analytics/views.py", views_for_stage(stage))
        write_lf(build / "analytics/urls.py", urls_for_stage(stage))
        name, email = PEOPLE[who]
        when = (now - timedelta(days=days_ago, hours=3)).isoformat()
        git("add", "-A", cwd=build)
        git("commit", "-q", "-m", message, cwd=build, env={
            "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": when,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": when,
        })

    git("clone", "-q", "--bare", str(build), str(origin), cwd=var)
    git("clone", "-q", "-c", "core.autocrlf=false", str(origin), str(clone), cwd=var)
    rmtree(build)
    return origin, clone


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="delete and recreate existing repos")
    args = parser.parse_args()
    origin, clone = seed(DEFAULT_VAR, force=args.force)
    print(f"origin (acts as GitHub): {origin}")
    print(f"working clone:           {clone}\n")
    print(git("log", "--format=%h  %an  %ad  %s", "--date=short", cwd=clone))


if __name__ == "__main__":
    main()
