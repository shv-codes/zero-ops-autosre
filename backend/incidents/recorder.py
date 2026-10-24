"""Django-backed Recorder: what the agent reports ends up in the database."""
from __future__ import annotations

import logging
from typing import Any

from django.db import close_old_connections
from django.utils import timezone

from .models import (
    AgentStep,
    AuditLog,
    GuardrailResult,
    Incident,
    IncidentStatus,
    SandboxRun,
    TimelineEvent,
)

logger = logging.getLogger("autosre.recorder")

_TIMESTAMP_FIELDS = {
    IncidentStatus.READY_TO_MERGE: "ready_at",
    IncidentStatus.RESOLVED: "finished_at",
    IncidentStatus.ESCALATED: "finished_at",
}

# Agent-side results can carry very long text (sandbox logs); cap what we store per row.
MAX_TEXT = 60_000


def _clip(text: str, limit: int = MAX_TEXT) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 40] + f"\n... [truncated {len(text) - limit} chars]"


class DjangoRecorder:
    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        self._status = Incident.objects.values_list("status", flat=True).get(pk=incident_id)

    # -- helpers -----------------------------------------------------------
    def _incident_qs(self):
        close_old_connections()
        return Incident.objects.filter(pk=self.incident_id)

    def _exists(self) -> bool:
        return self._incident_qs().exists()

    # -- Recorder interface -------------------------------------------------
    def event(self, tag: str, message: str, **data: Any) -> None:
        if not self._exists():
            return
        TimelineEvent.objects.create(
            incident_id=self.incident_id, tag=tag, message=message, state=self._status, data=data
        )
        logger.info("[%s] %s %s", self.incident_id, tag, message)

    def set_status(self, status: str) -> None:
        current = self._incident_qs().values_list("status", flat=True).first()
        if current is None:
            return
        # A force-stop (or a finished run) must not be overwritten by a later step.
        if current in ("RESOLVED", "ESCALATED") and status not in ("RESOLVED", "ESCALATED"):
            self._status = current
            return
        previous, self._status = self._status, status
        fields: dict[str, Any] = {"status": status}
        ts_field = _TIMESTAMP_FIELDS.get(status)
        if ts_field:
            fields[ts_field] = timezone.now()
        self._incident_qs().update(**fields)
        self.audit("transition", {"from": previous, "to": status})

    def update(self, **fields: Any) -> None:
        if fields and self._exists():
            self._incident_qs().update(**fields)

    def agent_step(self, *, task, attempt, step, tool, args, ok, result, thought=""):
        if not self._exists():
            return
        AgentStep.objects.create(
            incident_id=self.incident_id, task=task, attempt=attempt, step=step, tool=tool,
            args=args, ok=ok, result=_clip(result, 20_000), thought=_clip(thought, 4_000),
        )

    def sandbox_run(self, *, task, attempt, result):
        if not self._exists():
            return
        SandboxRun.objects.create(
            incident_id=self.incident_id,
            task=task,
            attempt=attempt,
            engine=result.get("engine", "unknown"),
            isolated=bool(result.get("isolated")),
            passed=bool(result.get("passed")),
            reproduced=result.get("reproduced"),
            exit_code=int(result.get("exit_code", -1)),
            timed_out=bool(result.get("timed_out")),
            duration_seconds=float(result.get("duration_seconds", 0)),
            output=_clip(result.get("output", "")),
            limits=result.get("limits", {}),
        )

    def guardrail(self, *, attempt, check_id, name, passed, details):
        if not self._exists():
            return
        GuardrailResult.objects.create(
            incident_id=self.incident_id, attempt=attempt, check_id=check_id,
            name=name, passed=passed, details=details,
        )

    def audit(self, kind: str, payload: dict) -> None:
        if not self._exists():
            return
        AuditLog.objects.create(incident_id=self.incident_id, kind=kind, payload=payload)

    def timeline(self) -> list[dict]:
        return list(
            TimelineEvent.objects.filter(incident_id=self.incident_id).values("ts", "tag", "message", "state")
        )
