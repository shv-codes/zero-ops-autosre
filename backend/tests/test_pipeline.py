"""Phase 6: the full workflow incl. the outer loop (TC-8, TC-9, TC-13 offline)."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.coding.llm import LLMUnavailable
from agent.pipeline import AgentDeps, PipelineConfig, run_pipeline
from agent.ports import MemoryRecorder
from correlation.correlator import GitCorrelator
from delivery.providers import DeliveryError, LocalProvider
from demo.teammate import push_teammate_change
from sandbox.runner import SubprocessSandbox
from workspace.gitcmd import GitError, git

from .fakes import FakeAdapter

LOG_LINES = [
    {"level": "INFO", "logger": "victim.request", "msg": "request", "path": "/api/reports/user-activity/",
     "status": 200, "view": "analytics.views.user_activity_report"},
    {"level": "WARNING", "logger": "analytics.pool", "msg": "report pool has 40 connections checked out"},
    {"level": "ERROR", "logger": "django.request", "msg": "Internal Server Error: /api/reports/user-activity/",
     "path": "/api/reports/user-activity/", "status": 500,
     "exc": 'File "/app/analytics/views.py", line 34, in user_activity_report\n'
            "psycopg2.OperationalError: FATAL: sorry, too many clients already"},
]


class Scenario:
    """Drives the outer loop: a teammate pushes a conflict, later a human merges."""

    def __init__(self, provider, recorder, conflict=True, merge=True):
        self.provider, self.rec = provider, recorder
        self.conflict, self.merge = conflict, merge
        self.sleeps = 0

    def sleep(self, _seconds):
        self.sleeps += 1
        ready_count = self.rec.statuses.count("READY_TO_MERGE")
        if self.conflict and ready_count == 1 and not getattr(self, "pushed", False):
            push_teammate_change(self.provider)
            self.pushed = True
        elif self.merge and ready_count >= (2 if self.conflict else 1):
            pr = sorted(Path(self.provider.store).glob("pr-*.json"))[-1]
            self.provider.human_merge(json.loads(pr.read_text())["number"])
        if self.sleeps > 50:
            raise RuntimeError("scenario did not converge")


@pytest.fixture
def env(seeded_repo, tmp_path):
    origin, clone = seeded_repo
    log = tmp_path / "victim.log"
    log.write_text("\n".join(json.dumps(line) for line in LOG_LINES) + "\n")
    provider = LocalProvider(origin, tmp_path / "prs")
    return origin, clone, provider, log, tmp_path


def make_deps(env, *, mode="cached", live_factory=None, provider=None, scenario_kw=None, adapter=None):
    origin, clone, local, log, tmp = env
    provider = provider or local
    rec = MemoryRecorder("INC-E2E")
    scenario = Scenario(local, rec, **(scenario_kw or {}))

    def no_live():
        raise LLMUnavailable("no API key configured for provider 'groq'")

    deps = AgentDeps(
        recorder=rec, adapter=adapter or FakeAdapter(leaked=88), log_path=str(log),
        correlator=GitCorrelator(clone), provider=provider, sandbox=SubprocessSandbox(timeout=120),
        mode=mode, live_client_factory=live_factory or no_live,
        config=PipelineConfig(pr_poll_seconds=0, pr_watch_timeout=600, deliveries_dir=tmp / "deliveries",
                              work_dir=tmp / "work", secret_values=["autosre_agent_pw"]),
        started_at=datetime.now(timezone.utc),
        baseline=lambda: {"total": 10, "active": 2, "idle": 8, "idle_in_transaction": 0},
        sleep=scenario.sleep,
    )
    return deps, rec, scenario


def test_full_loop_fix_pr_conflict_ready_merged_tc13(env):
    origin, clone, provider, log, tmp = env
    deps, rec, _ = make_deps(env)
    state = run_pipeline("INC-E2E", {"metric": "pg_connections", "value": 98, "source": "pg-monitor"}, deps)

    assert state.get("error") is None, state.get("error")
    assert state["outcome"] == "merged"
    assert rec.statuses == [
        "DIAGNOSING", "MITIGATING", "CORRELATING", "PATCHING",
        "TESTING_IN_SANDBOX", "PATCHING", "TESTING_IN_SANDBOX", "PATCHING",  # attempt 1 fails, attempt 2 passes
        "PR_CREATED", "READY_TO_MERGE",
        "UPDATING_PR", "TESTING_IN_SANDBOX", "PATCHING", "PR_CREATED",      # outer loop resolves the conflict
        "READY_TO_MERGE", "RESOLVED",
    ]
    # mitigation ended only the app's sessions
    assert rec.fields["mitigation"]["terminated"] == 88
    # correlation found Charlie
    assert rec.fields["suspect"]["commit"]["author"] == "Charlie Contributor"
    # fix verified with self-healing
    assert rec.fields["fix"]["attempts"] == 2 and rec.fields["fix"]["risk"] == "Low"
    # PR exists on the fix branch, never on main
    pr = rec.fields["pull_request"]
    assert pr["head_branch"] == "autosre/fix-user-activity-report" and pr["base_branch"] == "main"
    # the merged main contains BOTH the fix and the teammate's LIMIT 100
    views = git("show", "main:analytics/views.py", cwd=origin)
    assert "with report_pool.connection() as conn:" in views and "LIMIT 100" in views
    assert "report_pool.acquire()" not in views.split("def user_activity_report")[1]
    assert "<<<<<<<" not in views
    assert "tests/test_user_activity_releases_connection.py" in git("ls-tree", "-r", "--name-only", "main", cwd=origin)
    # post-mortem has all required sections (FR-7.4)
    body = rec.fields["postmortem"]
    for section in ("### Summary", "### Impact", "### Root cause", "### Fix", "### Verification", "### Timeline", "### Prevention"):
        assert section in body
    assert "NOT-isolated subprocess fallback" in body  # never claims isolation it did not have
    assert "autosre_agent_pw" not in json.dumps(rec.audits)  # secrets never reach prompts
    assert any(e["tag"] == "LOOP" and "repaired" in e["message"] for e in rec.events)


def test_llm_unreachable_falls_back_to_cached_tc8(env):
    deps, rec, _ = make_deps(env, mode="live", scenario_kw={"conflict": False})
    state = run_pipeline("INC-E2E", {}, deps)
    assert state["outcome"] == "merged"
    assert rec.fields["llm"]["fallback_used"] is True
    assert any("using CACHED" in e["message"] for e in rec.events)


def test_delivery_failure_saves_patch_locally_tc9(env):
    origin, clone, local, log, tmp = env

    class BrokenProvider(LocalProvider):
        def open_pr(self, *a, **kw):
            raise DeliveryError("GitHub API error: 502 Bad Gateway")

    deps, rec, _ = make_deps(env, provider=BrokenProvider(origin, tmp / "prs2"))
    state = run_pipeline("INC-E2E", {}, deps)
    assert state["outcome"] == "escalated"
    assert rec.statuses[-1] == "ESCALATED"
    bundle = tmp / "deliveries" / "INC-E2E"
    assert "with report_pool.connection()" in (bundle / "fix.patch").read_text()
    assert "human action required" in (bundle / "postmortem.md").read_text()


def _git_identity(repo: Path) -> None:
    git("config", "user.email", "test@example.com", cwd=repo)
    git("config", "user.name", "Test", cwd=repo)
    git("config", "commit.gpgsign", "false", cwd=repo)


def _commit_file(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content)
    git("add", name, cwd=repo)
    git("commit", "-m", message, cwd=repo)


def _empty_repo(path: Path) -> None:
    path.mkdir()
    git("init", "-b", "main", cwd=path)
    _git_identity(path)


def test_publish_merge_replaces_a_diverged_autosre_branch(tmp_path):
    origin = tmp_path / "origin.git"
    github = tmp_path / "github.git"
    git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("init", "--bare", "-b", "main", str(github), cwd=tmp_path)
    work = tmp_path / "work"
    _empty_repo(work)
    git("remote", "add", "origin", origin.as_posix(), cwd=work)
    _commit_file(work, "f.txt", "base\n", "base")
    git("push", "origin", "main", cwd=work)
    git("checkout", "-b", "autosre/fix-user-activity-report", cwd=work)
    _commit_file(work, "f.txt", "fix-v1\n", "fix v1")
    git("push", "origin", "autosre/fix-user-activity-report", cwd=work)
    git("remote", "add", "github", github.as_posix(), cwd=work)
    git("push", "github", "main", cwd=work)
    git("push", "github", "autosre/fix-user-activity-report", cwd=work)
    _commit_file(work, "f.txt", "fix-v2\n", "fix v2")
    git("push", "origin", "autosre/fix-user-activity-report", cwd=work)
    other = tmp_path / "other"
    git("clone", github.as_posix(), other.as_posix(), cwd=tmp_path)
    _git_identity(other)
    git("checkout", "autosre/fix-user-activity-report", cwd=other)
    _commit_file(other, "f.txt", "github-only\n", "github only")
    git("push", "origin", "HEAD", cwd=other)

    class Mirror(LocalProvider):
        def github_repo(self):
            return "example/victim-service"

        def _mirror_url(self):
            return github.as_posix()

    Mirror(origin, tmp_path / "prs").publish_merge("autosre/fix-user-activity-report", "main")
    local = git("rev-parse", "refs/heads/autosre/fix-user-activity-report", cwd=origin).strip()
    remote = git("rev-parse", "refs/heads/autosre/fix-user-activity-report", cwd=github).strip()
    assert local == remote
    assert "fix-v2" in git("show", f"{remote}:f.txt", cwd=github)


def test_publish_merge_does_not_overwrite_a_non_autosre_branch(tmp_path):
    origin = tmp_path / "origin.git"
    github = tmp_path / "github.git"
    git("init", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    git("init", "--bare", "-b", "main", str(github), cwd=tmp_path)
    work = tmp_path / "work"
    _empty_repo(work)
    git("remote", "add", "origin", origin.as_posix(), cwd=work)
    _commit_file(work, "f.txt", "base\n", "base")
    git("push", "origin", "main", cwd=work)
    git("checkout", "-b", "feature/manual", cwd=work)
    _commit_file(work, "f.txt", "local\n", "local")
    git("push", "origin", "feature/manual", cwd=work)
    git("remote", "add", "github", github.as_posix(), cwd=work)
    git("push", "github", "main", cwd=work)
    git("push", "github", "feature/manual", cwd=work)
    _commit_file(work, "f.txt", "local-v2\n", "local v2")
    git("push", "origin", "feature/manual", cwd=work)
    other = tmp_path / "other"
    git("clone", github.as_posix(), other.as_posix(), cwd=tmp_path)
    _git_identity(other)
    git("checkout", "feature/manual", cwd=other)
    _commit_file(other, "f.txt", "remote-only\n", "remote only")
    git("push", "origin", "HEAD", cwd=other)
    remote_before = git("rev-parse", "refs/heads/feature/manual", cwd=github).strip()

    class Mirror(LocalProvider):
        def github_repo(self):
            return "example/victim-service"

        def _mirror_url(self):
            return github.as_posix()

    with pytest.raises(GitError, match="rejected|fetch first"):
        Mirror(origin, tmp_path / "prs").publish_merge("feature/manual", "main")
    assert git("rev-parse", "refs/heads/feature/manual", cwd=github).strip() == remote_before


def test_unreachable_database_escalates(env):
    deps, rec, _ = make_deps(env, adapter=FakeAdapter(reachable=False))
    state = run_pipeline("INC-E2E", {}, deps)
    assert state["outcome"] == "escalated"
    assert "cannot read telemetry" in rec.fields["escalation_reason"]
