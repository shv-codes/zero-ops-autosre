"""
AutoSRE's memory.

Every incident, every step the agent takes, every sandbox run, guardrail verdict and
LLM prompt/response is stored here. That gives us:
  * the live dashboard (it reads these rows),
  * the audit trail (NFR-O1),
  * replay mode (FR-9.2) — a recorded run is just these rows played back.
"""
import secrets

from django.db import models
from django.utils import timezone


def new_incident_id() -> str:
    return f"INC-{secrets.token_hex(3).upper()}"


class IncidentStatus(models.TextChoices):
    ALERT_RECEIVED = "ALERT_RECEIVED"
    MITIGATING = "MITIGATING"
    DIAGNOSING = "DIAGNOSING"
    CORRELATING = "CORRELATING"
    PATCHING = "PATCHING"
    TESTING_IN_SANDBOX = "TESTING_IN_SANDBOX"
    PR_CREATED = "PR_CREATED"
    UPDATING_PR = "UPDATING_PR"  # outer loop: resolving conflicts / fixing CI
    AWAITING_APPROVAL = "AWAITING_APPROVAL"  # review mode: waiting for a human decision
    READY_TO_MERGE = "READY_TO_MERGE"  # agent is done; a human must merge
    RESOLVED = "RESOLVED"  # the fix was merged by a human
    ESCALATED = "ESCALATED"  # handed to a human with all evidence


# States in which the agent thread is still (or should still be) working.
ACTIVE_STATUSES = {
    IncidentStatus.ALERT_RECEIVED,
    IncidentStatus.MITIGATING,
    IncidentStatus.DIAGNOSING,
    IncidentStatus.CORRELATING,
    IncidentStatus.PATCHING,
    IncidentStatus.TESTING_IN_SANDBOX,
    IncidentStatus.PR_CREATED,
    IncidentStatus.UPDATING_PR,
    IncidentStatus.AWAITING_APPROVAL,
}
FINAL_STATUSES = {IncidentStatus.RESOLVED, IncidentStatus.ESCALATED}


class RunMode(models.TextChoices):
    CACHED = "cached"
    LIVE = "live"
    REPLAY = "replay"


class Incident(models.Model):
    id = models.CharField(primary_key=True, max_length=32, default=new_incident_id, editable=False)
    status = models.CharField(max_length=32, choices=IncidentStatus.choices, default=IncidentStatus.ALERT_RECEIVED)
    mode = models.CharField(max_length=16, choices=RunMode.choices, default=RunMode.CACHED)
    source = models.CharField(max_length=32, default="webhook")  # monitor | webhook | demo | replay
    dedupe_key = models.CharField(max_length=128, db_index=True)

    alert = models.JSONField(default=dict)
    telemetry = models.JSONField(default=dict)  # snapshot at diagnosis time
    mitigation = models.JSONField(default=dict)  # stop-the-bleeding result
    diagnosis = models.JSONField(default=dict)
    suspect = models.JSONField(default=dict)  # suspect commit, files, line range, confidence, evidence
    project_profile = models.JSONField(default=dict)  # how to install/test the target project

    attempt = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    fix = models.JSONField(default=dict)  # summary, risk, risk_reason, files, regression_test
    unified_diff = models.TextField(blank=True, default="")

    branch = models.CharField(max_length=128, blank=True, default="")
    pull_request = models.JSONField(default=dict)  # provider, number, url, state, mergeable, checks, rounds
    postmortem = models.TextField(blank=True, default="")

    approval_mode = models.CharField(max_length=16, default="autonomous")  # autonomous | review
    pending_approval = models.JSONField(default=dict, blank=True)  # {gate, title, details, requested_at} while waiting
    llm = models.JSONField(default=dict)  # provider, model, fallback_used
    sandbox_isolated = models.BooleanField(null=True)
    escalation_reason = models.TextField(blank=True, default="")
    signature = models.JSONField(default=dict, blank=True)  # incident memory: query hash + file + function
    related_incidents = models.JSONField(default=list, blank=True)  # past incidents with the same signature
    ai_card = models.JSONField(default=dict, blank=True)  # responsible-AI card (decision maker, data shared, ...)

    created_at = models.DateTimeField(default=timezone.now)
    mitigated_at = models.DateTimeField(null=True, blank=True)
    pr_opened_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.id} [{self.status}]"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def mttr_seconds(self) -> int | None:
        """Alert -> verified fix delivered and ready to merge."""
        end = self.ready_at or (self.finished_at if self.status == IncidentStatus.ESCALATED else None)
        if not end:
            return None
        return int((end - self.created_at).total_seconds())

    @property
    def time_to_mitigate_seconds(self) -> int | None:
        if not self.mitigated_at:
            return None
        return int((self.mitigated_at - self.created_at).total_seconds())


class TimelineEvent(models.Model):
    """One line on the dashboard terminal (FR-8.2): [TAG] message."""

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="events")
    ts = models.DateTimeField(default=timezone.now)
    tag = models.CharField(max_length=16)  # ALERT | MITIGATE | DIAG | CORR | AGENT | GUARD | TEST | PR | LOOP
    message = models.TextField()
    state = models.CharField(max_length=32)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["id"]


class AgentStep(models.Model):
    """One tool call made by the coding agent (read_file, edit_file, run_tests, ...)."""

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="agent_steps")
    ts = models.DateTimeField(default=timezone.now)
    task = models.CharField(max_length=32)  # fix | resolve_conflict | fix_ci
    attempt = models.PositiveIntegerField(default=1)
    step = models.PositiveIntegerField()
    thought = models.TextField(blank=True, default="")
    tool = models.CharField(max_length=64)
    args = models.JSONField(default=dict)
    ok = models.BooleanField(default=True)
    result = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["id"]


class SandboxRun(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="sandbox_runs")
    ts = models.DateTimeField(default=timezone.now)
    task = models.CharField(max_length=32, default="fix")
    attempt = models.PositiveIntegerField(default=1)
    engine = models.CharField(max_length=32)  # docker | subprocess
    isolated = models.BooleanField()
    passed = models.BooleanField()
    reproduced = models.BooleanField(null=True)  # did the regression test fail on the old code?
    exit_code = models.IntegerField()
    timed_out = models.BooleanField(default=False)
    duration_seconds = models.FloatField(default=0)
    output = models.TextField(blank=True, default="")
    limits = models.JSONField(default=dict)

    class Meta:
        ordering = ["id"]


class GuardrailResult(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="guardrail_results")
    ts = models.DateTimeField(default=timezone.now)
    attempt = models.PositiveIntegerField(default=0)
    check_id = models.CharField(max_length=64)
    name = models.CharField(max_length=128)
    passed = models.BooleanField()
    details = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["id"]


class AuditLog(models.Model):
    """Append-only record of every decision (NFR-O1)."""

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="audit", null=True, blank=True)
    ts = models.DateTimeField(default=timezone.now)
    kind = models.CharField(max_length=32)  # transition | prompt | response | tool | patch | sandbox | guardrail | delivery | error | config
    payload = models.JSONField(default=dict)

    class Meta:
        ordering = ["id"]


class TelemetrySample(models.Model):
    """Connection counts sampled by the monitor; feeds the live graph (FR-8.6)."""

    ts = models.DateTimeField(default=timezone.now, db_index=True)
    active = models.PositiveIntegerField()
    idle = models.PositiveIntegerField()
    idle_in_transaction = models.PositiveIntegerField()
    total = models.PositiveIntegerField()
    max_connections = models.PositiveIntegerField()

    class Meta:
        ordering = ["-ts"]


class RuntimeConfig(models.Model):
    """Settings the dashboard can change at runtime (single row)."""

    mode = models.CharField(max_length=16, choices=RunMode.choices, default=RunMode.CACHED)
    max_attempts = models.PositiveIntegerField(default=3)
    llm_provider = models.CharField(max_length=32, default="groq")
    alert_threshold = models.FloatField(default=0.9)
    monitor_enabled = models.BooleanField(default=True)
    approval_mode = models.CharField(max_length=16, default="autonomous")  # autonomous | review
    # GitHub App connection (filled by the "Connect GitHub" install flow)
    github_installation_id = models.BigIntegerField(null=True, blank=True)
    github_account = models.CharField(max_length=128, blank=True, default="")
    github_install_state = models.CharField(max_length=64, blank=True, default="")
    github_install_state_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls) -> "RuntimeConfig":
        from django.conf import settings

        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "mode": settings.AUTOSRE["MODE"],
                "max_attempts": settings.AUTOSRE["MAX_ATTEMPTS"],
                "llm_provider": settings.LLM["PROVIDER"],
                "alert_threshold": settings.AUTOSRE["ALERT_THRESHOLD"],
                "monitor_enabled": settings.AUTOSRE["MONITOR_ENABLED"],
            },
        )
        # A previous boot stored an inline env comment as the provider name
        # ("groq # groq | nvidia"), so the configured API key never matched.
        known = set(settings.LLM["PROVIDERS"])
        if obj.llm_provider not in known:
            obj.llm_provider = settings.LLM["PROVIDER"] if settings.LLM["PROVIDER"] in known else "groq"
            obj.save(update_fields=["llm_provider", "updated_at"])
        return obj
