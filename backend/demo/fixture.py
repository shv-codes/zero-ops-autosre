"""
In-memory database and a canned log for the prototype.

Play prototype does not need PostgreSQL or the victim container. The numbers and the
log lines are the same shape the live incident produces, so diagnosis and correlation
still run.
"""
from __future__ import annotations

import json
from pathlib import Path

from telemetry import ConnectionSnapshot, DatabaseAdapter, SessionInfo

LEAK_QUERY = (
    "SELECT user_id, COUNT(*) AS events, MAX(created_at) AS last_seen "
    "FROM analytics_useractivity GROUP BY user_id ORDER BY events DESC LIMIT 50"
)

LOG_LINES = [
    {"level": "INFO", "logger": "victim.request", "msg": "request", "path": "/api/reports/user-activity/",
     "status": 200, "view": "analytics.views.user_activity_report"},
    {"level": "WARNING", "logger": "analytics.pool", "msg": "report pool has 40 connections checked out"},
    {"level": "ERROR", "logger": "django.request", "msg": "Internal Server Error: /api/reports/user-activity/",
     "path": "/api/reports/user-activity/", "status": 500,
     "exc": 'File "/app/analytics/views.py", line 34, in user_activity_report\n'
            "psycopg2.OperationalError: FATAL: sorry, too many clients already"},
]


class FixtureAdapter(DatabaseAdapter):
    """98 of 100 connections, with the victim app holding leaked sessions."""

    engine = "fixture"

    def __init__(self, leaked: int = 89, healthy_idle: int = 6, max_connections: int = 100):
        self.max_connections = max_connections
        self.healthy_idle = healthy_idle
        self.sessions = [
            SessionInfo(pid=1000 + i, application_name="victim-service:reports", user="victim_app",
                        state="idle in transaction", state_age_seconds=30.0 + i, xact_age_seconds=31.0 + i,
                        query=LEAK_QUERY)
            for i in range(leaked)
        ]
        self.sessions.append(
            SessionInfo(pid=999, application_name="psql", user="dba", state="idle in transaction",
                        state_age_seconds=40.0, xact_age_seconds=40.0, query="BEGIN")
        )
        self.terminated: list[int] = []

    def snapshot(self) -> ConnectionSnapshot:
        return ConnectionSnapshot(
            active=2, idle=self.healthy_idle, idle_in_transaction=len(self.sessions), other=0,
            max_connections=self.max_connections,
            by_application={"victim-service:reports": len(self.sessions) - 1, "psql": 1},
        )

    def stuck_sessions(self, min_idle_seconds: int, app_prefix: str | None = None) -> list[SessionInfo]:
        return [s for s in self.sessions
                if s.state_age_seconds >= min_idle_seconds
                and (app_prefix is None or s.application_name.startswith(app_prefix))]

    def terminate(self, pids: list[int], app_prefix: str, min_idle_seconds: int) -> list[int]:
        allowed = {s.pid for s in self.stuck_sessions(min_idle_seconds, app_prefix)}
        done = [p for p in pids if p in allowed]
        self.terminated.extend(done)
        self.sessions = [s for s in self.sessions if s.pid not in done]
        return done


def _seed_module():
    import sys

    from django.conf import settings

    scripts = str(settings.REPO_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.append(scripts)  # appended, so scripts/demo.py never shadows backend/demo
    import seed_victim_repo

    return seed_victim_repo


def history_problems(origin: Path, base_branch: str) -> list[str]:
    """Ways the local demo repo differs from the freshly seeded history ([] = pristine).

    Every prototype run leaves traces: a fix branch, a teammate commit on main, sometimes a
    merged fix. The recorded agent decisions expect Charlie's original leak, so the next
    play must start from exactly the seeded state.
    """
    from workspace.gitcmd import GitError, git

    seed = _seed_module()
    if not (origin / "HEAD").exists():
        return ["origin repo missing"]
    try:
        subjects = git("log", "--format=%s", base_branch, cwd=origin).splitlines()
        branches = git("for-each-ref", "--format=%(refname:short)", "refs/heads", cwd=origin).split()
        views = git("show", f"{base_branch}:analytics/views.py", cwd=origin)
    except GitError as exc:
        return [f"unreadable: {exc}"]
    problems = []
    expected = [c[2] for c in reversed(seed.COMMITS)]
    if subjects != expected:
        problems.append(f"{base_branch} has {len(subjects)} commit(s), expected the {len(expected)} seeded ones")
    extra = [b for b in branches if b != base_branch]
    if extra:
        problems.append(f"leftover branches: {', '.join(extra)}")
    if views.replace("\r\n", "\n") != seed.views_for_stage(4):
        problems.append("analytics/views.py differs from Charlie's original leak")
    return problems


def ensure_pristine_history() -> list[str]:
    """Re-seed the local demo repo unless it is exactly the seeded history.
    Returns the problems that were fixed ([] when nothing needed doing)."""
    from django.conf import settings

    if settings.DELIVERY["PROVIDER"] != "local":
        return []
    problems = history_problems(Path(settings.DELIVERY["LOCAL_ORIGIN"]), settings.TARGET_REPO["BASE_BRANCH"])
    if problems:
        _seed_module().seed(Path(settings.VAR_DIR), force=True)
    return problems


# Backwards-compatible name used elsewhere.
ensure_leaky_history = ensure_pristine_history


def prototype_log_path() -> Path:
    from django.conf import settings

    path = Path(settings.VAR_DIR) / "logs" / "prototype.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in LOG_LINES) + "\n", encoding="utf-8")
    return path
