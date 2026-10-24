"""
Recorded agent decisions for cached mode (FR-9.1): the demo works with no Wi-Fi or API key.

Only the *decisions* are recorded. Every tool still runs for real: files are really
edited, guardrails really checked, the sandbox really runs the tests. That is why the
first attempt genuinely fails and the retry genuinely passes.

The fix recording mirrors a mistake real models often make: calling release() after
`return` (it never runs), then correcting it to a context manager once the failing
test output shows the connection is still leaked.
"""
from __future__ import annotations

from .llm import ScriptedClient

VICTIM_FILE = "analytics/views.py"
REGRESSION_TEST_PATH = "tests/test_user_activity_releases_connection.py"

REGRESSION_TEST = '''from django.test import Client


def test_user_activity_report_returns_connection_to_pool(fake_report_pool):
    """Regression test for the incident: every request must give its pooled connection back."""
    client = Client()
    for _ in range(5):
        assert client.get("/api/reports/user-activity/").status_code == 200
    stats = fake_report_pool.stats()
    assert stats["in_use"] == 0, f"{stats['in_use']} report connection(s) were never returned to the pool"
    assert stats["opened"] == 1
'''

RETURN_LINE = '    return JsonResponse({"status": "success", "count": len(data), "data": data})'

FLAWED_FIX = RETURN_LINE + "\n    report_pool.release(conn)"

LEAKY_BODY = '''    conn = report_pool.acquire()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, COUNT(*) AS events, MAX(created_at) AS last_seen "
        "FROM analytics_useractivity GROUP BY user_id ORDER BY events DESC LIMIT 50"
    )
    rows = cursor.fetchall()
    data = [{"user_id": r[0], "events": r[1], "last_seen": str(r[2])} for r in rows]
'''

FIXED_BODY = '''    with report_pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, COUNT(*) AS events, MAX(created_at) AS last_seen "
            "FROM analytics_useractivity GROUP BY user_id ORDER BY events DESC LIMIT 50"
        )
        rows = cursor.fetchall()
    data = [{"user_id": r[0], "events": r[1], "last_seen": str(r[2])} for r in rows]
'''


def fix_parts(source: str) -> tuple[str, str, str] | None:
    """From the real file text: (leaky block, fixed block, return line), or None if the pattern is absent.

    Built from the code that is actually checked out, so the recorded edits still match when
    the surrounding lines differ (for example a teammate changed LIMIT 50 to LIMIT 100).
    """
    lines = source.replace("\r\n", "\n").split("\n")
    try:
        start = next(i for i, line in enumerate(lines) if "report_pool.acquire()" in line)
        fetch = next(i for i in range(start, len(lines)) if "cursor.fetchall()" in lines[i])
        ret = next(i for i in range(fetch, len(lines)) if lines[i].strip().startswith("return JsonResponse"))
    except StopIteration:
        return None
    indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    leaky = "\n".join(lines[start:ret]) + "\n"
    fixed_lines = [f"{indent}with report_pool.connection() as conn:"]
    fixed_lines += [("    " + line) if line.strip() else line for line in lines[start + 1: fetch + 1]]
    fixed_lines += lines[fetch + 1: ret]
    return leaky, "\n".join(fixed_lines) + "\n", lines[ret]


def fix_recording(leaky_body: str = LEAKY_BODY, fixed_body: str = FIXED_BODY,
                  return_line: str = RETURN_LINE) -> ScriptedClient:
    flawed_fix = return_line + "\n" + return_line[: len(return_line) - len(return_line.lstrip())] + "report_pool.release(conn)"
    return ScriptedClient([
        ("Start with the suspect function the correlation pointed at.",
         "read_file", {"path": VICTIM_FILE}),
        ("It calls report_pool.acquire() but never gives the connection back. Check the pool API.",
         "read_file", {"path": "analytics/pool.py"}),
        ("See how other code in this repo uses the pool correctly.",
         "search", {"text": "report_pool.connection()"}),
        ("First, a regression test that reproduces the leak: after several requests nothing may stay checked out.",
         "write_file", {"path": REGRESSION_TEST_PATH, "content": REGRESSION_TEST}),
        ("Release the connection when the view is done.",
         "edit_file", {"path": VICTIM_FILE, "old_text": return_line, "new_text": flawed_fix}),
        ("Run the guardrails and the sandbox.",
         "run_tests", {}),
        ("The test still sees leaked connections: release() sits after `return`, so it never runs. "
         "Use the pool's context manager like top_pages does, so the connection is returned even on errors.",
         "edit_file", {"path": VICTIM_FILE, "old_text": leaky_body + flawed_fix, "new_text": fixed_body + return_line}),
        ("Verify again.",
         "run_tests", {}),
        ("Tests pass and the regression test fails on the old code.",
         "finish", {
             "summary": "user_activity_report acquired a pooled database connection and never released it, so every "
                        "request left a session idle in transaction until PostgreSQL ran out of connections. The view "
                        "now uses `with report_pool.connection()`, which always returns the connection (even on errors), "
                        "and a regression test proves no connection stays checked out.",
             "risk": "Low",
             "risk_reason": "Three-line change that adopts the pool's existing context manager (already used by "
                            "top_pages); response format unchanged; full test suite passes.",
         }),
    ], name="victim-service-pool-leak")


def recording_for_fix(suspect: dict, source: str | None = None) -> ScriptedClient | None:
    """The recorded fix for the demo leak. With `source` (the file as checked out), the edits are
    derived from the real code, so they match even if nearby lines changed."""
    loc = suspect.get("location", {})
    if loc.get("file") != VICTIM_FILE or loc.get("function") != "user_activity_report":
        return None
    if source is None:
        return fix_recording()
    parts = fix_parts(source)
    return fix_recording(*parts) if parts else None


# --- outer loop: merge conflict with the demo teammate change (demo/teammate.py) ---------
CONFLICT_BLOCK = '''<<<<<<< HEAD
    with report_pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, COUNT(*) AS events, MAX(created_at) AS last_seen "
            "FROM analytics_useractivity GROUP BY user_id ORDER BY events DESC LIMIT 50"
        )
        rows = cursor.fetchall()
=======
    conn = report_pool.acquire()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, COUNT(*) AS events, MAX(created_at) AS last_seen "
        "FROM analytics_useractivity GROUP BY user_id ORDER BY events DESC LIMIT 100"
    )
    rows = cursor.fetchall()
>>>>>>> origin/main
'''

RESOLVED_BLOCK = '''    with report_pool.connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, COUNT(*) AS events, MAX(created_at) AS last_seen "
            "FROM analytics_useractivity GROUP BY user_id ORDER BY events DESC LIMIT 100"
        )
        rows = cursor.fetchall()
'''


def conflict_parts(text: str) -> tuple[str, str] | None:
    """From a file with conflict markers: (whole conflict block, resolution keeping BOTH intents).

    Ours = the fix (context manager). Theirs = the teammate's edit on the old leaky code.
    The resolution keeps our structure and takes the teammate's LIMIT value.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("<<<<<<< "))
        mid = next(i for i in range(start, len(lines)) if lines[i] == "=======")
        end = next(i for i in range(mid, len(lines)) if lines[i].startswith(">>>>>>> "))
    except StopIteration:
        return None
    ours, theirs = "\n".join(lines[start + 1: mid]), "\n".join(lines[mid + 1: end])
    if "report_pool.connection()" not in ours:
        return None
    import re

    limit = re.search(r"LIMIT \d+", theirs)
    resolved = re.sub(r"LIMIT \d+", limit.group(0), ours) if limit else ours
    return "\n".join(lines[start: end + 1]) + "\n", resolved + "\n"


def conflict_recording(block: str = CONFLICT_BLOCK, resolved: str = RESOLVED_BLOCK) -> ScriptedClient:
    return ScriptedClient([
        ("Look at the conflict markers.",
         "read_file", {"path": VICTIM_FILE}),
        ("Our side wraps the query in the pool's context manager; the teammate changed the query LIMIT on the "
         "old leaky code. Keep both: the context manager AND the teammate's new LIMIT.",
         "edit_file", {"path": VICTIM_FILE, "old_text": block, "new_text": resolved}),
        ("Re-verify the merged result.",
         "run_tests", {}),
        ("Merged cleanly; tests pass.",
         "finish", {
             "summary": "Merged the latest main into the fix branch. Kept the teammate's change (top 100 users) "
                        "and the leak fix (connection always returned via the context manager).",
             "risk": "Low",
             "risk_reason": "Conflict was limited to one query block; both intents preserved; suite passes.",
         }),
    ], name="victim-service-merge-conflict")


def recording_for_conflict(conflicts: dict[str, str]) -> ScriptedClient | None:
    """conflicts = {path: file text with markers}. Built from the real markers, not a fixed snapshot."""
    if set(conflicts) != {VICTIM_FILE}:
        return None
    parts = conflict_parts(conflicts[VICTIM_FILE])
    return conflict_recording(*parts) if parts else None
