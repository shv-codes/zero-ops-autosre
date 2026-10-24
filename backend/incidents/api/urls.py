from django.urls import path

from . import demo_views, github_views, stream, views

urlpatterns = [
    path("health", views.health, name="health"),
    path("system", views.system_status, name="system"),
    path("alerts", views.receive_alert, name="alerts"),
    path("incidents", views.list_incidents, name="incidents"),
    path("incidents/<str:incident_id>", views.get_incident, name="incident"),
    path("incidents/<str:incident_id>/stream", stream.incident_stream, name="incident-stream"),
    path("incidents/<str:incident_id>/diff", views.get_diff, name="incident-diff"),
    path("incidents/<str:incident_id>/postmortem", views.get_postmortem, name="incident-postmortem"),
    path("incidents/<str:incident_id>/steps", views.get_steps, name="incident-steps"),
    path("incidents/<str:incident_id>/sandbox-runs", views.get_sandbox_runs, name="incident-sandbox-runs"),
    path("incidents/<str:incident_id>/audit", views.export_audit, name="incident-audit"),
    path("incidents/<str:incident_id>/merge", demo_views.human_merge, name="incident-merge"),
    path("incidents/<str:incident_id>/decision", views.decide, name="incident-decision"),
    path("incidents/<str:incident_id>/stop", views.force_stop, name="incident-stop"),
    path("guardrails", views.get_guardrails, name="guardrails"),
    path("telemetry/connections", views.telemetry_current, name="telemetry-current"),
    path("telemetry/connections/history", views.telemetry_history, name="telemetry-history"),
    path("config", views.config_view, name="config"),
    path("github/status", github_views.github_status, name="github-status"),
    path("github/connect", github_views.github_connect, name="github-connect"),
    path("github/callback", github_views.github_callback, name="github-callback"),
    path("github/disconnect", github_views.github_disconnect, name="github-disconnect"),
    path("demo/prototype", demo_views.prototype, name="demo-prototype"),
    path("demo/trigger", demo_views.trigger, name="demo-trigger"),
    path("demo/traffic", demo_views.traffic_status, name="demo-traffic"),
    path("demo/replay", demo_views.replay, name="demo-replay"),
    path("demo/teammate-push", demo_views.teammate_push, name="demo-teammate-push"),
    path("demo/reset", demo_views.reset, name="demo-reset"),
]
