import os

import pytest
from django.test import Client

from incidents.models import AuditLog, Incident, IncidentStatus, RuntimeConfig, TimelineEvent
from incidents.recorder import DjangoRecorder

pytestmark = pytest.mark.django_db


def test_health_uses_envelope():
    body = Client().get("/api/v1/health").json()
    assert body["error"] is None
    assert body["data"]["status"] == "healthy"
    assert "timestamp" in body["meta"]


def test_recorder_writes_events_transitions_and_timestamps():
    inc = Incident.objects.create(dedupe_key="k")
    rec = DjangoRecorder(inc.id)

    rec.set_status(IncidentStatus.DIAGNOSING)
    rec.event("DIAG", "looking at pg_stat_activity", sessions=3)
    rec.update(diagnosis={"idle_in_transaction": 90})
    rec.set_status(IncidentStatus.READY_TO_MERGE)

    inc.refresh_from_db()
    assert inc.status == IncidentStatus.READY_TO_MERGE
    assert inc.diagnosis == {"idle_in_transaction": 90}
    assert inc.ready_at is not None and inc.mttr_seconds is not None

    event = TimelineEvent.objects.get(incident=inc)
    assert (event.tag, event.state, event.data) == ("DIAG", "DIAGNOSING", {"sessions": 3})
    transitions = [a.payload["to"] for a in AuditLog.objects.filter(incident=inc, kind="transition")]
    assert transitions == ["DIAGNOSING", "READY_TO_MERGE"]


def test_runtime_config_is_a_singleton():
    a = RuntimeConfig.load()
    b = RuntimeConfig.load()
    assert a.pk == b.pk == 1


def test_runtime_config_repairs_provider_polluted_by_env_comment():
    RuntimeConfig.objects.create(pk=1, llm_provider="groq                 # groq | nvidia", mode="live")
    cfg = RuntimeConfig.load()
    assert cfg.llm_provider == "groq"


def test_env_inline_comment_is_not_part_of_the_value(tmp_path, monkeypatch):
    from autosre_api.settings import _load_env

    path = tmp_path / ".env"
    path.write_text("LLM_PROVIDER=groq                 # groq | nvidia\nGROQ_MODEL=openai/gpt-oss-120b\n", encoding="utf-8")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    _load_env(path)
    assert os.environ["LLM_PROVIDER"] == "groq"
