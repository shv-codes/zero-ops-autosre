"""Phase 7: Django wiring + REST API + SSE + replay, driven by a real (cached-mode) incident run."""
import json

import pytest
from asgiref.sync import async_to_sync
from django.test import AsyncClient, Client

from incidents import wiring
from incidents.models import Incident, RunMode
from incidents.replay import export_incident, replay_into
from incidents.services import ingest_alert

from .fakes import FakeAdapter
from .test_pipeline import LOG_LINES

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def configured(settings, seeded_repo, tmp_path, monkeypatch):
    origin, clone = seeded_repo
    log = tmp_path / "victim.log"
    log.write_text("\n".join(json.dumps(line) for line in LOG_LINES) + "\n")
    settings.VAR_DIR = tmp_path / "var"
    settings.TARGET_APP = {**settings.TARGET_APP, "LOG_PATH": str(log)}
    settings.TARGET_REPO = {**settings.TARGET_REPO, "PATH": str(clone)}
    settings.DELIVERY = {**settings.DELIVERY, "PROVIDER": "local", "LOCAL_ORIGIN": str(origin), "GITHUB_REPO": ""}
    settings.SANDBOX = {**settings.SANDBOX, "ENGINE": "subprocess", "WORK_DIR": str(tmp_path / "sbx")}
    settings.AUTOSRE = {**settings.AUTOSRE, "PR_POLL_SECONDS": 0.05, "PR_WATCH_TIMEOUT_SECONDS": 1}
    adapter = FakeAdapter(leaked=88)
    monkeypatch.setattr(wiring, "get_adapter", lambda: adapter)
    monkeypatch.setattr("incidents.api.views.get_adapter", lambda: adapter)
    return origin, clone, adapter


@pytest.fixture
def finished_incident(configured):
    incident, _ = ingest_alert({"source": "pg-monitor", "metric": "pg_connections", "value": 98, "max": 100},
                               start=False)
    wiring.run_incident(incident.id)
    incident.refresh_from_db()
    return incident


def body(resp):
    data = resp.json()
    assert data["error"] is None, data["error"]
    return data["data"]


def test_incident_runs_to_ready_to_merge_via_django(finished_incident):
    inc = finished_incident
    assert inc.status == "READY_TO_MERGE", inc.escalation_reason
    assert inc.mode == RunMode.CACHED
    assert inc.mitigated_at and inc.pr_opened_at and inc.ready_at and inc.mttr_seconds is not None
    assert inc.pull_request["draft"] is False and inc.pull_request["provider"] == "local"
    assert inc.sandbox_isolated is False  # subprocess fallback is reported honestly


def test_api_endpoints(finished_incident):
    c, iid = Client(), finished_incident.id
    detail = body(c.get(f"/api/v1/incidents/{iid}"))
    assert detail["status"] == "READY_TO_MERGE"
    assert detail["suspect"]["commit"]["author"] == "Charlie Contributor"
    assert "commit_diff" not in detail["suspect"]
    assert [e["tag"] for e in detail["timeline"]][:2] == ["ALERT", "DIAG"]

    assert body(c.get("/api/v1/incidents"))[0]["id"] == iid
    assert "+    with report_pool.connection() as conn:" in body(c.get(f"/api/v1/incidents/{iid}/diff"))["diff"]
    assert "### Root cause" in body(c.get(f"/api/v1/incidents/{iid}/postmortem"))["markdown"]
    steps = body(c.get(f"/api/v1/incidents/{iid}/steps"))
    assert any(s["tool"] == "edit_file" for s in steps)
    runs = body(c.get(f"/api/v1/incidents/{iid}/sandbox-runs"))
    assert [r["passed"] for r in runs] == [False, True]

    checks = {g["id"]: g for g in body(c.get(f"/api/v1/guardrails?incident_id={iid}"))["checks"]}
    assert checks["diff_size"]["status"] == "passed"
    assert checks["human_gate"]["status"] == "passed"
    assert checks["sandbox_isolation"]["status"] == "failed"  # NOT isolated without Docker — shown, not hidden
    assert checks["retry_cap"]["details"] == "Attempt 2 of 3."

    audit = c.get(f"/api/v1/incidents/{iid}/audit")
    assert audit["Content-Disposition"].endswith(f'{iid}-audit.json"')
    bundle = json.loads(audit.content)
    assert {a["kind"] for a in bundle["audit"]} >= {"transition", "prompt", "response"}

    telemetry = body(c.get("/api/v1/telemetry/connections"))
    assert telemetry["idle_in_transaction"] >= 1 and telemetry["max"] == 100
    assert c.get("/api/v1/incidents/INC-NOPE").status_code == 404


def test_human_merge_button_and_stream(finished_incident):
    c, iid = Client(), finished_incident.id
    assert body(c.post(f"/api/v1/incidents/{iid}/merge"))["merged"] is True
    Incident.objects.filter(pk=iid).update(status="RESOLVED")  # the watcher would do this on its next poll

    async def read_stream():
        resp = await AsyncClient().get(f"/api/v1/incidents/{iid}/stream")
        assert resp["Content-Type"] == "text/event-stream"
        return "".join([chunk.decode() async for chunk in resp.streaming_content])

    text = async_to_sync(read_stream)()
    assert "event: timeline" in text and "Suspect commit" in text
    assert 'event: status\ndata: {"status": "RESOLVED"}' in text and "event: end" in text


def test_config_validation():
    c = Client()
    assert body(c.patch("/api/v1/config", {"mode": "live", "max_attempts": 2}, content_type="application/json"))["mode"] == "live"
    bad = c.patch("/api/v1/config", {"max_attempts": 99}, content_type="application/json").json()
    assert bad["error"]["code"] == "INVALID_CONFIG"


def test_prototype_endpoint_does_not_need_the_victim(configured, settings, monkeypatch):
    settings.SANDBOX = {**settings.SANDBOX, "ENGINE": "cached"}
    launched = []
    monkeypatch.setattr("incidents.runner.launch", lambda incident_id: launched.append(incident_id))
    c = Client()
    system = body(c.get("/api/v1/system"))
    assert system["sandbox"] == {"engine": "cached", "isolated": False, "setting": "cached"}
    resp = c.post("/api/v1/demo/prototype", {}, content_type="application/json")
    assert resp.status_code == 201, resp.content
    data = body(resp)
    assert data["incident"]["source"] == "prototype"
    assert data["incident"]["mode"] == "cached"
    assert data["incident"]["approval_mode"] == "autonomous"
    assert launched == [data["incident"]["id"]]
    assert "docker" not in data["message"].lower()
    again = c.post("/api/v1/demo/prototype", {}, content_type="application/json")
    assert again.status_code == 409


def test_prototype_repairs_the_teammate_commit(configured, settings, monkeypatch):
    """Fixture database, cached checks, a real commit on main, then the conflict is repaired."""
    from workspace.gitcmd import git

    origin, _, _ = configured
    settings.AUTOSRE = {**settings.AUTOSRE, "PR_WATCH_TIMEOUT_SECONDS": 180}
    incident, created = ingest_alert(
        {"source": "prototype", "metric": "pg_connections", "value": 98, "max": 100},
        source="prototype", start=False, mode="cached", approval_mode="autonomous",
    )
    assert created
    calls = {"n": 0}

    def hurry(_seconds):
        calls["n"] += 1
        current = Incident.objects.get(pk=incident.id)
        if current.status == "READY_TO_MERGE" and (current.pull_request or {}).get("rounds", 0) >= 1:
            from delivery.providers import get_provider

            get_provider().human_merge(int(current.pull_request["number"]))
        if calls["n"] > 12:
            raise RuntimeError(f"prototype did not converge ({current.status}: {current.escalation_reason})")

    monkeypatch.setattr("incidents.wiring.time.sleep", hurry)
    wiring.run_incident(incident.id)
    incident.refresh_from_db()
    assert incident.status == "RESOLVED", incident.escalation_reason
    assert incident.mitigation.get("terminated", 0) > 0
    assert incident.sandbox_isolated is False

    runs = list(incident.sandbox_runs.order_by("id"))
    assert [run.engine for run in runs] == ["cached"] * len(runs)
    assert [run.passed for run in runs[:2]] == [False, True]
    assert runs[-1].task == "resolve_conflict" and runs[-1].passed is True

    review = incident.pull_request["reviews"][-1]
    assert review["author"] == "Dana Developer"
    assert "top 100" in review["message"]
    assert review["conflicts"] is True
    assert "analytics/views.py" in review["conflict_files"]
    assert review["sandbox"]["passed"] is True and review["sandbox"]["engine"] == "cached"
    assert any("manage.py check" in command for command in review["sandbox"]["commands"])
    assert any(command.strip() == "python -m pytest" for command in review["sandbox"]["commands"])
    assert "context manager" in review["repair_summary"]
    assert any("New commit" in event.message and "Dana Developer" in event.message for event in incident.events.all())

    views = git("show", "main:analytics/views.py", cwd=origin)
    assert "with report_pool.connection() as conn:" in views and "LIMIT 100" in views
    assert "<<<<<<<" not in views
    assert "cached checks" in incident.postmortem


def test_force_stop_and_delete_one_incident(configured):
    incident, created = ingest_alert({"source": "pg-monitor", "metric": "pg_connections", "value": 98, "max": 100},
                                     start=False)
    assert created
    c = Client()
    stopped = body(c.post(f"/api/v1/incidents/{incident.id}/stop"))
    assert stopped == {"stopped": True, "id": incident.id}
    incident.refresh_from_db()
    assert incident.status == "ESCALATED" and incident.escalation_reason == "Force-stopped."

    from incidents.recorder import DjangoRecorder
    DjangoRecorder(incident.id).set_status("PATCHING")
    incident.refresh_from_db()
    assert incident.status == "ESCALATED"

    deleted = body(c.delete(f"/api/v1/incidents/{incident.id}"))
    assert deleted == {"deleted": True, "id": incident.id}
    assert c.get(f"/api/v1/incidents/{incident.id}").status_code == 404
    assert c.post(f"/api/v1/incidents/{incident.id}/stop").status_code == 404
    assert c.delete(f"/api/v1/incidents/{incident.id}").status_code == 404


def test_replay_reproduces_recorded_run(finished_incident, tmp_path, monkeypatch):
    path = export_incident(finished_incident, tmp_path / "rec.json")
    monkeypatch.setattr("incidents.replay.RECORDING", path)
    replay, _ = ingest_alert({"source": "replay", "metric": "pg_replay"}, source="replay", start=False)
    Incident.objects.filter(pk=replay.pk).update(mode=RunMode.REPLAY)
    replay_into(Incident.objects.get(pk=replay.pk), speed=1000, sleep=lambda s: None)
    replay.refresh_from_db()
    assert replay.status == "READY_TO_MERGE"
    assert replay.events.count() == finished_incident.events.count() + 2  # + opening alert + replay banner line
    assert replay.sandbox_runs.count() == 2 and replay.unified_diff == finished_incident.unified_diff
