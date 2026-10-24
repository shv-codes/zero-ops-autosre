"""
Incident lifecycle entry points used by the API, the monitor and the demo controls.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction

from .models import FINAL_STATUSES, Incident, RuntimeConfig, TimelineEvent

logger = logging.getLogger("autosre.incidents")


def normalize_alert(payload: dict) -> dict:
    """Accept the SRS 6.3 payload (and tolerate missing fields)."""
    payload = payload if isinstance(payload, dict) else {}
    return {
        "source": str(payload.get("source", "webhook"))[:64],
        "severity": str(payload.get("severity", "critical"))[:32],
        "metric": str(payload.get("metric", "pg_connections"))[:64],
        "value": payload.get("value"),
        "max": payload.get("max"),
        "service": str(payload.get("service", settings.TARGET_DB["NAME"]))[:64],
        "timestamp": payload.get("timestamp"),
        "labels": payload.get("labels") if isinstance(payload.get("labels"), dict) else {},
    }


def dedupe_key_for(alert: dict) -> str:
    return f"{alert['metric']}:{alert['service']}"


def ingest_alert(payload: dict, source: str = "webhook", start: bool = True,
                 mode: str | None = None, approval_mode: str | None = None) -> tuple[Incident, bool]:
    """
    Create an incident for an alert and start the agent (FR-1.3).

    While an incident for the same problem is still open (anything except RESOLVED or
    ESCALATED), new alerts are recorded on it and ignored (FR-1.4 / TC-12), so we never
    run two fixes for the same problem at once.
    Returns (incident, created).
    """
    alert = normalize_alert(payload)
    key = dedupe_key_for(alert)
    config = RuntimeConfig.load()

    with transaction.atomic():
        existing = (
            Incident.objects.select_for_update()
            .filter(dedupe_key=key)
            .exclude(status__in=FINAL_STATUSES)
            .order_by("-created_at")
            .first()
        )
        if existing:
            TimelineEvent.objects.create(
                incident=existing, tag="ALERT", state=existing.status,
                message=f"Duplicate alert from {source} suppressed ({alert['metric']}={alert['value']}); incident already in progress.",
            )
            return existing, False

        incident = Incident.objects.create(
            dedupe_key=key, alert=alert, source=source, mode=mode or config.mode,
            max_attempts=config.max_attempts, approval_mode=approval_mode or config.approval_mode,
        )
        value = f"{alert['value']}/{alert['max']}" if alert["max"] else str(alert["value"])
        TimelineEvent.objects.create(
            incident=incident, tag="ALERT", state=incident.status,
            message=f"Alert from {alert['source']} ({alert['severity']}): {alert['metric']} = {value}. Incident opened.",
        )

    logger.info("Opened incident %s from %s", incident.id, source)
    if start:
        from .runner import launch

        transaction.on_commit(lambda: launch(incident.id))
    return incident, True
