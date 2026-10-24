"""Review mode: store the approval request on the incident and wait for the dashboard's decision."""
from __future__ import annotations

import time

from django.db import close_old_connections
from django.utils import timezone

from agent.approvals import ApprovalRequest, Decision

from .models import Incident, IncidentStatus
from .runner import stop_requested


class DjangoApprovalGate:
    mode = "review"

    def __init__(self, incident_id: str, recorder, timeout_seconds: float = 900, poll_seconds: float = 1.0,
                 sleep=time.sleep):
        self.incident_id = incident_id
        self.recorder = recorder
        self.timeout = timeout_seconds
        self.poll = poll_seconds
        self.sleep = sleep

    def request(self, req: ApprovalRequest) -> Decision:
        previous = getattr(self.recorder, "_status", None) or Incident.objects.get(pk=self.incident_id).status
        self.recorder.update(pending_approval={
            "gate": req.gate, "title": req.title, "details": req.details,
            "requested_at": timezone.now().isoformat(), "timeout_seconds": self.timeout, "decision": None,
        })
        self.recorder.set_status(IncidentStatus.AWAITING_APPROVAL)
        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                close_old_connections()
                if stop_requested(self.incident_id):
                    return Decision(approved=False, by="operator", note="Force-stopped.")
                pending = Incident.objects.values_list("pending_approval", flat=True).get(pk=self.incident_id) or {}
                choice = pending.get("decision")
                if choice in ("approve", "deny"):
                    return Decision(approved=choice == "approve", by=pending.get("decided_by") or "reviewer",
                                    note=pending.get("note", ""))
                self.sleep(self.poll)
            return Decision(approved=False, by="nobody", note="approval timed out", timed_out=True)
        finally:
            self.recorder.update(pending_approval={})
            self.recorder.set_status(previous)


def record_decision(incident: Incident, gate: str, decision: str, by: str, note: str = "") -> None:
    """Called by the API when a person clicks Approve / Deny."""
    pending = dict(incident.pending_approval or {})
    if not pending or pending.get("gate") != gate:
        raise ValueError("no pending approval for that gate")
    if pending.get("decision"):
        raise ValueError("this request was already decided")
    if decision not in ("approve", "deny"):
        raise ValueError("decision must be 'approve' or 'deny'")
    pending.update(decision=decision, decided_by=(by or "dashboard user")[:64], note=(note or "")[:500],
                   decided_at=timezone.now().isoformat())
    Incident.objects.filter(pk=incident.pk).update(pending_approval=pending)
