"""The judges' demo must work on every play, whatever earlier runs left behind."""
import pytest

from agent.coding.recordings import (
    CONFLICT_BLOCK,
    FIXED_BODY,
    LEAKY_BODY,
    RESOLVED_BLOCK,
    RETURN_LINE,
    conflict_parts,
    fix_parts,
    recording_for_conflict,
    recording_for_fix,
)
from demo.fixture import history_problems
from demo.teammate import push_teammate_change
from delivery.providers import LocalProvider
from workspace.gitcmd import git

SUSPECT = {"location": {"file": "analytics/views.py", "function": "user_activity_report"}}


def test_fix_parts_match_the_original_recording(seeded_repo):
    _, clone = seeded_repo
    leaky, fixed, ret = fix_parts((clone / "analytics/views.py").read_text())
    assert (leaky, fixed, ret) == (LEAKY_BODY, FIXED_BODY, RETURN_LINE)


def test_fix_recording_adapts_when_teammate_changed_limit(seeded_repo):
    """The INC-90C6F8 failure: main already had LIMIT 100, so the fixed recording no longer matched."""
    _, clone = seeded_repo
    source = (clone / "analytics/views.py").read_text().replace("LIMIT 50", "LIMIT 100")
    leaky, fixed, _ = fix_parts(source)
    assert "LIMIT 100" in leaky and "LIMIT 100" in fixed and "with report_pool.connection() as conn:" in fixed

    # Apply the two recorded edits exactly as the agent's edit_file tool would.
    edits = [args for _, tool, args in recording_for_fix(SUSPECT, source).steps if tool == "edit_file"]
    code = source
    for edit in edits:
        assert code.count(edit["old_text"]) == 1, "recorded edit must match the checked-out code exactly once"
        code = code.replace(edit["old_text"], edit["new_text"], 1)
    body = code.split("def user_activity_report")[1]
    assert "with report_pool.connection() as conn:" in body and "LIMIT 100" in body
    assert "report_pool.acquire()" not in body and "release(conn)" not in body


def test_conflict_resolution_is_derived_from_the_real_markers():
    assert conflict_parts(CONFLICT_BLOCK) == (CONFLICT_BLOCK, RESOLVED_BLOCK)
    other = CONFLICT_BLOCK.replace("LIMIT 100", "LIMIT 250")
    block, resolved = conflict_parts(other)
    assert block == other and "LIMIT 250" in resolved and "report_pool.connection()" in resolved
    assert recording_for_conflict({"analytics/views.py": other}) is not None
    assert conflict_parts("no markers here") is None


def test_history_check_detects_leftovers_from_previous_plays(seeded_repo, tmp_path):
    origin, _ = seeded_repo
    assert history_problems(origin, "main") == []

    push_teammate_change(LocalProvider(origin, tmp_path / "prs"))  # what an earlier play leaves on main
    git("branch", "autosre/fix-user-activity-report", "main", cwd=origin)
    problems = history_problems(origin, "main")
    assert any("commit(s)" in p for p in problems)
    assert any("leftover branches" in p for p in problems)
    assert any("views.py differs" in p for p in problems)


@pytest.mark.django_db
def test_prototype_endpoint_restores_repo_and_refuses_while_busy(settings, seeded_repo, tmp_path, monkeypatch):
    from django.test import Client

    from incidents import runner
    from incidents.models import Incident

    origin, clone = seeded_repo
    settings.VAR_DIR = origin.parent
    settings.DELIVERY = {**settings.DELIVERY, "PROVIDER": "local", "LOCAL_ORIGIN": str(origin)}
    settings.TARGET_REPO = {**settings.TARGET_REPO, "PATH": str(clone)}
    monkeypatch.setattr(runner, "launch", lambda incident_id: None)  # don't run the agent here
    push_teammate_change(LocalProvider(origin, tmp_path / "prs"))
    assert history_problems(origin, "main")

    c = Client()
    first = c.post("/api/v1/demo/prototype").json()
    assert first["error"] is None and first["data"]["repo_restored"]
    assert history_problems(origin, "main") == []  # every play starts from Charlie's original leak

    busy = c.post("/api/v1/demo/prototype")
    assert busy.status_code == 409 and Incident.objects.count() == 1
