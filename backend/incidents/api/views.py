"""REST API (/api/v1). Every response uses the {data, error, meta} envelope."""
from __future__ import annotations

import json
import time
from datetime import timedelta

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view

from telemetry import TelemetryUnavailable, get_adapter

from ..models import AuditLog, GuardrailResult, Incident, IncidentStatus, RunMode, RuntimeConfig, SandboxRun, TelemetrySample, TimelineEvent
from ..services import ingest_alert
from .envelope import fail, ok
from .serializers import (
    AgentStepSerializer,
    GuardrailResultSerializer,
    IncidentDetailSerializer,
    IncidentSummarySerializer,
    SandboxRunSerializer,
)


def _incident_or_404(incident_id):
    try:
        return Incident.objects.get(pk=incident_id), None
    except Incident.DoesNotExist:
        return None, fail("NOT_FOUND", f"Incident {incident_id} not found", 404)


@api_view(["GET"])
def health(request):
    return ok({"status": "healthy", "service": "autosre", "version": "2.0.0"})


# --- system status (what is configured / reachable) ----------------------------------------
_docker_cache: dict = {"at": 0.0, "ok": False}


def _docker_available() -> bool:
    if time.monotonic() - _docker_cache["at"] > 15:
        from sandbox.runner import DockerSandbox

        _docker_cache.update(at=time.monotonic(), ok=DockerSandbox.available())
    return _docker_cache["ok"]


@api_view(["GET"])
def system_status(request):
    from ..monitor import get_monitor

    config = RuntimeConfig.load()
    llm_cfg = settings.LLM["PROVIDERS"].get(config.llm_provider, {})
    delivery = settings.DELIVERY
    engine = settings.SANDBOX["ENGINE"]
    docker_ok = _docker_available() if engine in ("auto", "docker") else False
    if engine == "cached":
        sandbox = {"engine": "cached", "isolated": False, "setting": engine}
    elif docker_ok:
        sandbox = {"engine": "docker", "isolated": True, "setting": engine}
    else:
        sandbox = {"engine": "subprocess", "isolated": False, "setting": engine}
    monitor = get_monitor()
    try:
        get_adapter().snapshot()
        db = {"reachable": True, "error": None}
    except TelemetryUnavailable as exc:
        db = {"reachable": False, "error": str(exc)}
    return ok({
        "mode": config.mode,
        "llm": {"provider": config.llm_provider, "model": llm_cfg.get("MODEL"), "configured": bool(llm_cfg.get("API_KEY"))},
        "delivery": {
            "provider": delivery["PROVIDER"],
            "target": delivery["GITHUB_REPO"] if delivery["PROVIDER"] == "github" else delivery["LOCAL_ORIGIN"],
            "configured": bool((delivery["GITHUB_APP_ID"] or delivery["GITHUB_TOKEN"]) and delivery["GITHUB_REPO"])
            if delivery["PROVIDER"] == "github" else True,
            "auth_mode": ("app" if delivery["GITHUB_APP_ID"] else "token" if delivery["GITHUB_TOKEN"] else "none")
            if delivery["PROVIDER"] == "github" else "local",
        },
        "sandbox": sandbox,
        "database": {**db, "engine": settings.TARGET_DB["ENGINE"], "host": settings.TARGET_DB["HOST"]},
        "monitor": {"running": bool(monitor), "last_error": getattr(monitor, "last_error", None),
                    "threshold": config.alert_threshold, "enabled": config.monitor_enabled},
        "victim": {"base_url": settings.TARGET_APP["BASE_URL"]},
    })


# --- alerts & incidents ------------------------------------------------------------------------
@api_view(["POST"])
def receive_alert(request):
    """Alert webhook (FR-1.1). Duplicate alerts for an open incident return 200 with created=false."""
    incident, created = ingest_alert(request.data, source="webhook")
    return ok({"created": created, "incident": IncidentSummarySerializer(incident).data}, status=201 if created else 200)


@api_view(["GET"])
def list_incidents(request):
    qs = Incident.objects.all()[:50]
    return ok(IncidentSummarySerializer(qs, many=True).data)


@api_view(["GET", "DELETE"])
def get_incident(request, incident_id):
    if request.method == "DELETE":
        return _delete_incident(incident_id)
    inc, err = _incident_or_404(incident_id)
    return err or ok(IncidentDetailSerializer(inc).data)


@api_view(["GET"])
def get_diff(request, incident_id):
    inc, err = _incident_or_404(incident_id)
    return err or ok({"incident_id": inc.id, "diff": inc.unified_diff,
                      "suspect_commit_diff": (inc.suspect or {}).get("commit_diff", "")})


@api_view(["GET"])
def get_postmortem(request, incident_id):
    inc, err = _incident_or_404(incident_id)
    return err or ok({"incident_id": inc.id, "markdown": inc.postmortem})


@api_view(["GET"])
def get_steps(request, incident_id):
    inc, err = _incident_or_404(incident_id)
    return err or ok(AgentStepSerializer(inc.agent_steps.all(), many=True).data)


@api_view(["GET"])
def get_sandbox_runs(request, incident_id):
    inc, err = _incident_or_404(incident_id)
    return err or ok(SandboxRunSerializer(inc.sandbox_runs.all(), many=True).data)


@api_view(["GET"])
def export_audit(request, incident_id):
    """Full audit trail as a downloadable JSON file (NFR-O1, AO-9)."""
    inc, err = _incident_or_404(incident_id)
    if err:
        return err
    bundle = {
        "incident": IncidentDetailSerializer(inc).data,
        "agent_steps": AgentStepSerializer(inc.agent_steps.all(), many=True).data,
        "sandbox_runs": SandboxRunSerializer(inc.sandbox_runs.all(), many=True).data,
        "guardrails": GuardrailResultSerializer(inc.guardrail_results.all(), many=True).data,
        "audit": list(AuditLog.objects.filter(incident=inc).values("ts", "kind", "payload")),
        "exported_at": timezone.now().isoformat(),
    }
    resp = HttpResponse(json.dumps(bundle, indent=2, default=str), content_type="application/json")
    resp["Content-Disposition"] = f'attachment; filename="{inc.id}-audit.json"'
    return resp


# --- guardrails checklist (dashboard panel) ------------------------------------------------------
GUARDRAIL_ORDER = [
    ("diff_size", "Diff size (<= 50 changed lines)"),
    ("file_allowlist", "File allowlist (suspect commit scope)"),
    ("secret_scan", "No secrets in patch"),
    ("dangerous_patterns", "Dangerous pattern blocklist"),
    ("syntax", "Changed files parse"),
    ("prompt_injection", "Prompt-injection screen"),
    ("sandbox_isolation", "Sandbox isolation"),
    ("retry_cap", "Retry cap"),
    ("human_gate", "No direct push to main; human merges"),
]


def guardrail_checklist(inc: Incident | None) -> list[dict]:
    latest = {}
    if inc:
        for g in GuardrailResult.objects.filter(incident=inc).order_by("id"):
            latest[g.check_id] = g
    run = SandboxRun.objects.filter(incident=inc).order_by("-id").first() if inc else None
    checks = []
    for check_id, name in GUARDRAIL_ORDER:
        if check_id == "sandbox_isolation":
            if run is None:
                checks.append({"id": check_id, "name": name, "status": "pending", "passed": None,
                               "details": "No sandbox run yet."})
            elif run.engine == "cached":
                checks.append({"id": check_id, "name": "Cached checks", "status": "passed", "passed": True,
                               "details": "Recorded manage.py check and pytest results. No Docker container."})
            else:
                lim = run.limits or {}
                details = (f"Container: network {lim.get('network')}, {lim.get('host_mounts')} host mounts, "
                           f"{lim.get('memory')} RAM, {lim.get('cpus')} CPU, {lim.get('timeout_seconds')}s timeout, non-root."
                           if run.isolated else "NOT ISOLATED: Docker unavailable, subprocess fallback used.")
                checks.append({"id": check_id, "name": name, "status": "passed" if run.isolated else "failed",
                               "passed": run.isolated, "details": details})
        elif check_id == "retry_cap":
            if inc is None or inc.attempt == 0:
                checks.append({"id": check_id, "name": f"Retry cap (<= {inc.max_attempts if inc else 3} attempts)",
                               "status": "pending", "passed": None, "details": "No attempts yet."})
            else:
                within = inc.attempt <= inc.max_attempts and inc.status != "ESCALATED"
                checks.append({"id": check_id, "name": f"Retry cap (<= {inc.max_attempts} attempts)",
                               "status": "passed" if within else "failed", "passed": within,
                               "details": f"Attempt {inc.attempt} of {inc.max_attempts}."})
        elif check_id in latest:
            g = latest[check_id]
            checks.append({"id": check_id, "name": g.name, "status": "passed" if g.passed else "failed",
                           "passed": g.passed, "details": g.details, "attempt": g.attempt})
        else:
            checks.append({"id": check_id, "name": name, "status": "pending", "passed": None, "details": "Not evaluated yet."})
    for check_id, g in latest.items():  # extra checks (e.g. conflict markers) that appeared
        if check_id not in dict(GUARDRAIL_ORDER):
            checks.append({"id": check_id, "name": g.name, "status": "passed" if g.passed else "failed",
                           "passed": g.passed, "details": g.details, "attempt": g.attempt})
    return checks


@api_view(["GET"])
def get_guardrails(request):
    incident_id = request.GET.get("incident_id")
    inc = Incident.objects.filter(pk=incident_id).first() if incident_id else Incident.objects.first()
    return ok({"incident_id": inc.id if inc else None, "checks": guardrail_checklist(inc)})


# --- telemetry ------------------------------------------------------------------------------------
@api_view(["GET"])
def telemetry_current(request):
    try:
        snap = get_adapter().snapshot()
    except TelemetryUnavailable as exc:
        return fail("TELEMETRY_UNAVAILABLE", str(exc), 503)
    d = snap.as_dict()
    return ok({"active": d["active"], "idle": d["idle"], "idle_in_transaction": d["idle_in_transaction"],
               "other": d["other"], "total": d["total"], "max": d["max_connections"],
               "utilization": d["utilization"], "by_application": d["by_application"], "live": True})


@api_view(["GET"])
def telemetry_history(request):
    minutes = min(int(request.GET.get("minutes", 10)), 120)
    samples = TelemetrySample.objects.filter(ts__gte=timezone.now() - timedelta(minutes=minutes)).order_by("ts")
    return ok([
        {"timestamp": s.ts.isoformat(), "active": s.active, "idle": s.idle,
         "idle_in_transaction": s.idle_in_transaction, "total": s.total, "max": s.max_connections}
        for s in samples
    ])


# --- config ---------------------------------------------------------------------------------------
@api_view(["GET", "PATCH"])
def config_view(request):
    config = RuntimeConfig.load()
    if request.method == "PATCH":
        body = request.data or {}
        errors = []
        if "mode" in body:
            if body["mode"] in RunMode.values:
                config.mode = body["mode"]
            else:
                errors.append(f"mode must be one of {RunMode.values}")
        if "max_attempts" in body:
            try:
                value = int(body["max_attempts"])
                if not 1 <= value <= 5:
                    raise ValueError
                config.max_attempts = value
            except (TypeError, ValueError):
                errors.append("max_attempts must be an integer between 1 and 5")
        if "llm_provider" in body:
            if body["llm_provider"] in settings.LLM["PROVIDERS"]:
                config.llm_provider = body["llm_provider"]
            else:
                errors.append(f"llm_provider must be one of {list(settings.LLM['PROVIDERS'])}")
        if "alert_threshold" in body:
            try:
                value = float(body["alert_threshold"])
                if not 0.5 <= value <= 1.0:
                    raise ValueError
                config.alert_threshold = value
            except (TypeError, ValueError):
                errors.append("alert_threshold must be between 0.5 and 1.0")
        if "approval_mode" in body:
            if body["approval_mode"] in ("autonomous", "review"):
                config.approval_mode = body["approval_mode"]
            else:
                errors.append("approval_mode must be 'autonomous' or 'review'")
        if "monitor_enabled" in body:
            config.monitor_enabled = bool(body["monitor_enabled"])
        if errors:
            return fail("INVALID_CONFIG", "; ".join(errors), 400)
        config.save()
        AuditLog.objects.create(kind="config", payload={k: body[k] for k in body})
    return ok({"mode": config.mode, "max_attempts": config.max_attempts, "llm_provider": config.llm_provider,
               "alert_threshold": config.alert_threshold, "monitor_enabled": config.monitor_enabled,
               "approval_mode": config.approval_mode})


@api_view(["POST"])
def decide(request, incident_id):
    """Review mode: Approve / Deny the incident's pending request. Body: {gate, decision, by?, note?}."""
    from ..approvals import record_decision

    inc, err = _incident_or_404(incident_id)
    if err:
        return err
    body = request.data or {}
    try:
        record_decision(inc, str(body.get("gate", "")), str(body.get("decision", "")),
                        str(body.get("by", "")), str(body.get("note", "")))
    except ValueError as exc:
        return fail("INVALID_DECISION", str(exc), 409)
    AuditLog.objects.create(incident=inc, kind="approval_click", payload={k: body.get(k) for k in ("gate", "decision", "by", "note")})
    return ok({"recorded": True})


@api_view(["POST"])
def force_stop(request, incident_id):
    """Stop the running agent at its next checkpoint and mark the incident escalated."""
    from ..runner import request_stop

    inc, err = _incident_or_404(incident_id)
    if err:
        return err
    request_stop(incident_id)
    if inc.status not in (IncidentStatus.RESOLVED, IncidentStatus.ESCALATED):
        reason = "Force-stopped."
        Incident.objects.filter(pk=incident_id).exclude(
            status__in=[IncidentStatus.RESOLVED, IncidentStatus.ESCALATED]
        ).update(status=IncidentStatus.ESCALATED, escalation_reason=reason, finished_at=timezone.now(), pending_approval={})
        TimelineEvent.objects.create(incident_id=incident_id, tag="ALERT", state="ESCALATED", message=f"ESCALATED: {reason}")
    return ok({"stopped": True, "id": incident_id})


def _delete_incident(incident_id):
    """Remove one incident and its timeline, steps, and audit trail."""
    from ..runner import request_stop

    inc, err = _incident_or_404(incident_id)
    if err:
        return err
    if inc.status not in (IncidentStatus.RESOLVED, IncidentStatus.ESCALATED):
        request_stop(incident_id)
    Incident.objects.filter(pk=incident_id).delete()
    return ok({"deleted": True, "id": incident_id})
