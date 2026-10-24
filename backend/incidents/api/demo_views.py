"""
Demo controls (FR-8.5, NFR-U2). These simulate the outside world — traffic, a teammate,
a human reviewer — they never let AutoSRE itself skip a safety rule.
"""
from __future__ import annotations

import sys

from django.conf import settings
from rest_framework.decorators import api_view

from delivery.providers import DeliveryError, LocalProvider, get_provider
from demo.teammate import MESSAGE as TEAMMATE_COMMIT, push_teammate_change
from workspace.gitcmd import GitError
from demo.traffic import driver, victim_reachable
from telemetry import TelemetryUnavailable, get_adapter

from ..models import Incident, RunMode, TelemetrySample, TimelineEvent
from ..replay import recording_available
from ..services import ingest_alert
from .envelope import fail, ok
from .serializers import IncidentSummarySerializer


@api_view(["POST"])
def prototype(request):
    """One-click story: fixture database, cached checks, then a real conflicting commit."""
    from demo.fixture import ensure_pristine_history

    from ..models import FINAL_STATUSES, Incident
    from ..services import dedupe_key_for, normalize_alert

    # Check for an open incident BEFORE touching the repo, so a running incident is never disturbed.
    key = dedupe_key_for(normalize_alert({"metric": "pg_connections", "service": settings.TARGET_DB["NAME"]}))
    busy = Incident.objects.filter(dedupe_key=key).exclude(status__in=FINAL_STATUSES).order_by("-created_at").first()
    if busy:
        return fail("ALREADY_RUNNING", f"{busy.id} is still open ({busy.status}). Delete or stop it, then play again.", 409)
    # Every play starts from Charlie's original leak: wipe traces of earlier runs (fix branches,
    # teammate commits, merged fixes) so the recorded decisions match the code exactly.
    repaired = ensure_pristine_history()
    incident, created = ingest_alert(
        {"source": "prototype", "metric": "pg_connections", "value": 98, "max": 100,
         "severity": "critical", "service": settings.TARGET_DB["NAME"]},
        source="prototype", mode=RunMode.CACHED, approval_mode="autonomous",
    )
    if not created:
        return fail("ALREADY_RUNNING", f"{incident.id} is already open. Reset it before playing the prototype again.", 409)
    incident.refresh_from_db()
    fresh = " Demo repo restored to Charlie's original leak." if repaired else ""
    return ok({
        "incident": IncidentSummarySerializer(incident).data,
        "message": f"Prototype started. After the pull request is ready, a teammate commit lands on main.{fresh}",
        "repo_restored": repaired,
    }, status=201)


@api_view(["POST"])
def trigger(request):
    """Start realistic HTTP traffic. The victim leaks; the monitor opens the incident by itself."""
    base_url = settings.TARGET_APP["BASE_URL"]
    if not victim_reachable(base_url):
        return fail("VICTIM_UNREACHABLE", f"victim service is not reachable at {base_url} (docker compose up -d)", 503)
    body = request.data or {}
    status = driver.start(base_url, total=int(body.get("requests", 400)), concurrency=int(body.get("concurrency", 8)))
    return ok({"traffic": status, "message": "Traffic started. The Alert Monitor will open an incident when "
                                             f"connections pass {int(settings.AUTOSRE['ALERT_THRESHOLD'] * 100)}%."})


@api_view(["GET"])
def traffic_status(request):
    return ok(driver.status())


@api_view(["POST"])
def replay(request):
    if not recording_available():
        return fail("NO_RECORDING", "no recorded run yet: finish one live/cached run, then "
                                    "`python manage.py export_replay <incident_id>`", 409)
    incident, created = ingest_alert({"source": "replay", "metric": "pg_connections_replay", "value": 98, "max": 100},
                                     source="replay", start=False)
    if not created:
        return fail("ALREADY_RUNNING", f"replay {incident.id} is already running", 409)
    Incident.objects.filter(pk=incident.pk).update(mode=RunMode.REPLAY)
    from django.db import transaction

    from ..runner import launch

    transaction.on_commit(lambda: launch(incident.id))
    incident.refresh_from_db()
    return ok({"incident": IncidentSummarySerializer(incident).data}, status=201)


@api_view(["POST"])
def teammate_push(request):
    """Simulate a teammate pushing a conflicting change to main (local provider only)."""
    try:
        sha = push_teammate_change(get_provider())
    except DeliveryError as exc:
        return fail("NOT_AVAILABLE", str(exc), 409)
    for inc in Incident.objects.filter(status__in=["PR_CREATED", "READY_TO_MERGE", "UPDATING_PR"]):
        TimelineEvent.objects.create(incident=inc, tag="LOOP", state=inc.status,
                                     message=f"A teammate pushed \"{TEAMMATE_COMMIT}\" to main.")
    return ok({"sha": sha, "branch": "main", "message": TEAMMATE_COMMIT})


@api_view(["POST"])
def human_merge(request, incident_id):
    """The human reviewer's 'Merge' button for the local provider. AutoSRE never merges on its own."""
    inc = Incident.objects.filter(pk=incident_id).first()
    if not inc or not inc.pull_request.get("number"):
        return fail("NOT_FOUND", "incident has no pull request", 404)
    provider = get_provider()
    if not isinstance(provider, LocalProvider):
        return fail("NOT_AVAILABLE", "merge real GitHub pull requests on GitHub", 409)
    number = int(inc.pull_request["number"])
    try:
        data = provider._load(number)
        sha = provider._rev(data["base"]) if data["state"] == "merged" else provider.human_merge(number)
        data = provider._load(number)
        published = provider.publish_merge(data["head"], data["base"])
    except (DeliveryError, GitError) as exc:
        return fail("CANNOT_MERGE", str(exc), 409)
    pr = {**inc.pull_request, "state": "merged", "head_branch": data["head"], "base_branch": data["base"]}
    if published.get("url"):
        pr["url"] = published["url"]
    Incident.objects.filter(pk=inc.pk).update(status="RESOLVED", pull_request=pr)
    where = f" Pushed {data['head']} and {data['base']} to {published['repo']}." if published.get("mirrored") else ""
    TimelineEvent.objects.create(
        incident=inc, tag="PR", state="RESOLVED",
        message=f"Merged branch {data['head']} into {data['base']}.{where}",
    )
    return ok({
        "merged": True,
        "sha": sha,
        "branch": data["head"],
        "base": data["base"],
        "commit_message": f"Merge branch '{data['head']}' into {data['base']}",
        "github_url": published.get("url"),
    })


@api_view(["POST"])
def reset(request):
    """Stop traffic and end the victim's leaked sessions. Optionally clear incidents and re-seed the repo."""
    body = request.data or {}
    driver.stop()
    result = {"traffic_stopped": True}
    try:
        adapter = get_adapter()
        prefix = settings.TARGET_DB["APP_NAME_PREFIX"]
        stuck = adapter.stuck_sessions(0, prefix)
        result["sessions_ended"] = len(adapter.terminate([s.pid for s in stuck], prefix, 0))
    except TelemetryUnavailable as exc:
        result["sessions_ended"] = 0
        result["database_error"] = str(exc)
    if body.get("clear_incidents"):
        active = Incident.objects.filter(status__in=["DIAGNOSING", "MITIGATING", "CORRELATING", "PATCHING",
                                                     "TESTING_IN_SANDBOX", "UPDATING_PR"]).exists()
        if active:
            return fail("BUSY", "an incident is still being worked on; wait for it to finish", 409)
        result["incidents_deleted"] = Incident.objects.all().delete()[0]
        TelemetrySample.objects.all().delete()
    if body.get("reseed_repo"):
        if str(settings.REPO_ROOT / "scripts") not in sys.path:
            sys.path.append(str(settings.REPO_ROOT / "scripts"))  # never shadow backend packages
        from seed_victim_repo import seed

        seed(settings.VAR_DIR, force=True)
        result["repo_reseeded"] = True
    return ok(result)
