"""Phase 4: project profiles, workspace and sandbox (TC-7)."""
import json
import textwrap
from pathlib import Path

import pytest

from project.profile import ProfileError, load_profile
from sandbox.runner import CachedSandbox, DockerSandbox, SubprocessSandbox, plan_steps
from workspace.workspace import PathNotAllowed, Workspace

REGRESSION_TEST_PATH = "tests/test_user_activity_releases_connection.py"
REGRESSION_TEST = textwrap.dedent('''
    from django.test import Client


    def test_user_activity_report_returns_connection_to_pool(fake_report_pool):
        client = Client()
        for _ in range(5):
            assert client.get("/api/reports/user-activity/").status_code == 200
        stats = fake_report_pool.stats()
        assert stats["in_use"] == 0, f"{stats['in_use']} report connection(s) were never returned to the pool"
        assert stats["opened"] == 1
''').lstrip()

LEAK = '''    conn = report_pool.acquire()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, COUNT(*) AS events, MAX(created_at) AS last_seen "
        "FROM analytics_useractivity GROUP BY user_id ORDER BY events DESC LIMIT 50"
    )
    rows = cursor.fetchall()
'''
FIX = '''    with report_pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, COUNT(*) AS events, MAX(created_at) AS last_seen "
            "FROM analytics_useractivity GROUP BY user_id ORDER BY events DESC LIMIT 50"
        )
        rows = cursor.fetchall()
'''


@pytest.fixture
def workspace(seeded_repo, tmp_path):
    origin, _ = seeded_repo
    ws = Workspace.create(str(origin), "main", "autosre/fix-test", parent_dir=tmp_path / "ws")
    yield ws
    ws.cleanup()


# --- profiles ---------------------------------------------------------------------

def test_profile_from_autosre_yml(workspace):
    profile = load_profile(workspace.root)
    assert profile.source == "file" and profile.language == "python"
    assert profile.checks == ["python manage.py check"]
    assert profile.single_test_command("tests/test_x.py") == "python -m pytest tests/test_x.py"
    assert profile.image_tag(workspace.root).startswith("autosre-sandbox-victim-service:")


def test_profile_detection_for_other_stacks(tmp_path):
    node = tmp_path / "node"; node.mkdir()
    (node / "package.json").write_text(json.dumps({"scripts": {"test": "jest", "lint": "eslint ."}}))
    (node / "package-lock.json").write_text("{}")
    p = load_profile(node)
    assert (p.language, p.install, p.test, p.checks) == ("node", "npm ci", "npm test", ["npm run lint"])

    go = tmp_path / "go"; go.mkdir()
    (go / "go.mod").write_text("module x\n")
    assert load_profile(go).test == "go test ./..."

    empty = tmp_path / "empty"; empty.mkdir()
    with pytest.raises(ProfileError):
        load_profile(empty)


def test_profile_rejects_unknown_keys(tmp_path):
    (tmp_path / ".autosre.yml").write_text("language: python\nbase_image: x\ninstall: y\ntest: z\nrm_rf: true\n")
    with pytest.raises(ProfileError, match="unknown keys"):
        load_profile(tmp_path)


def test_image_tag_changes_with_dependencies(workspace):
    profile = load_profile(workspace.root)
    before = profile.image_tag(workspace.root)
    workspace.write_file("requirements.txt", workspace.read_file("requirements.txt") + "requests\n")
    assert profile.image_tag(workspace.root) != before


# --- workspace ----------------------------------------------------------------------

def test_workspace_is_a_branch_and_blocks_escapes(workspace):
    from workspace.gitcmd import git

    assert git("branch", "--show-current", cwd=workspace.root).strip() == "autosre/fix-test"
    for bad in ("../outside.txt", "/etc/passwd", "C:/Windows/x", ".git/config", ""):
        with pytest.raises(PathNotAllowed):
            workspace.resolve(bad)


def test_workspace_diff_includes_new_files(workspace):
    workspace.write_file(REGRESSION_TEST_PATH, REGRESSION_TEST)
    views = workspace.read_file("analytics/views.py")
    workspace.write_file("analytics/views.py", views.replace(LEAK, FIX))
    changed = workspace.changed_files()
    assert set(changed) == {"analytics/views.py", REGRESSION_TEST_PATH}
    assert changed[REGRESSION_TEST_PATH].is_new


# --- sandbox (subprocess engine; Docker version below) ------------------------------------

def _prepare(workspace, tmp_path, fixed: bool):
    workspace.write_file(REGRESSION_TEST_PATH, REGRESSION_TEST)
    if fixed:
        workspace.write_file("analytics/views.py", workspace.read_file("analytics/views.py").replace(LEAK, FIX))
    original = workspace.export_tree(workspace.base_sha, tmp_path / "original")
    (original / REGRESSION_TEST_PATH).write_text(REGRESSION_TEST)
    return load_profile(workspace.root), original


def test_cached_sandbox_fails_the_leak_and_passes_the_fix(workspace, tmp_path):
    profile, original = _prepare(workspace, tmp_path, fixed=False)
    leaked = CachedSandbox().run(profile, workspace.root, original, REGRESSION_TEST_PATH)
    assert leaked["engine"] == "cached" and leaked["isolated"] is False
    assert leaked["reproduced"] is True and leaked["passed"] is False and leaked["failed_step"] == "test"
    assert "python manage.py check" in leaked["output"] and "pytest" in leaked["output"]
    assert "never returned to the pool" in leaked["output"] and "NOT ISOLATED" not in leaked["output"]

    # The recorded first attempt puts release() after return. The connection is still leaked.
    views = workspace.read_file("analytics/views.py")
    return_line = '    return JsonResponse({"status": "success", "count": len(data), "data": data})'
    workspace.write_file("analytics/views.py", views.replace(return_line, return_line + "\n    report_pool.release(conn)", 1))
    flawed = CachedSandbox().run(profile, workspace.root, original, REGRESSION_TEST_PATH)
    assert flawed["passed"] is False and flawed["reproduced"] is True

    clean = (original / "analytics/views.py").read_text(encoding="utf-8").replace(LEAK, FIX)
    workspace.write_file("analytics/views.py", clean)
    fixed = CachedSandbox().run(profile, workspace.root, original, REGRESSION_TEST_PATH)
    assert fixed["passed"] is True and fixed["reproduced"] is True and fixed["exit_code"] == 0
    commands = [step["command"] for step in fixed["steps"]]
    assert "python manage.py check" in commands and "python -m pytest" in commands

    # Conflict repair keeps the context manager and the teammate's LIMIT 100.
    workspace.write_file("analytics/views.py", clean.replace("LIMIT 50", "LIMIT 100", 1))
    resolved = CachedSandbox().run(profile, workspace.root, original, REGRESSION_TEST_PATH)
    assert resolved["passed"] is True and resolved["failed_step"] is None


def test_plan_steps_order(workspace):
    steps = plan_steps(load_profile(workspace.root), REGRESSION_TEST_PATH)
    assert [s.name for s in steps] == ["reproduce", "check_1", "test"]
    assert steps[0].tree == "original" and steps[0].expect_failure


def test_subprocess_sandbox_reproduces_bug_and_rejects_unfixed_code(workspace, tmp_path):
    profile, original = _prepare(workspace, tmp_path, fixed=False)
    result = SubprocessSandbox(timeout=120).run(profile, workspace.root, original, REGRESSION_TEST_PATH)
    assert result["reproduced"] is True
    assert result["passed"] is False and result["failed_step"] == "test"
    assert "never returned to the pool" in result["output"]
    assert result["isolated"] is False and "NOT ISOLATED" in result["output"]


def test_subprocess_sandbox_passes_fixed_code(workspace, tmp_path):
    profile, original = _prepare(workspace, tmp_path, fixed=True)
    result = SubprocessSandbox(timeout=120).run(profile, workspace.root, original, REGRESSION_TEST_PATH)
    assert result["reproduced"] is True
    assert result["passed"] is True and result["exit_code"] == 0, result["output"]


def test_sandbox_timeout_tc7(workspace, tmp_path):
    workspace.write_file("tests/test_slow.py", "import time\n\ndef test_slow():\n    time.sleep(30)\n")
    profile = load_profile(workspace.root)
    result = SubprocessSandbox(timeout=8).run(profile, workspace.root, None, None)
    assert result["timed_out"] is True and result["passed"] is False and result["exit_code"] == 124


@pytest.mark.docker
@pytest.mark.skipif(not DockerSandbox.available(), reason="Docker engine not running")
def test_docker_sandbox_end_to_end(workspace, tmp_path):
    profile, original = _prepare(workspace, tmp_path, fixed=True)
    result = DockerSandbox(timeout=120).run(profile, workspace.root, original, REGRESSION_TEST_PATH)
    assert result["isolated"] is True and result["limits"]["network"] == "none"
    assert result["reproduced"] is True
    assert result["passed"] is True, result["output"]
