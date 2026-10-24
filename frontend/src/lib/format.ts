import type { IncidentStatus } from "@/types/api"

export const clock = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""

export function duration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—"
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return m < 60 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`
}

export const secondsBetween = (from?: string | null, to?: string | null) =>
  from ? ((to ? new Date(to).getTime() : Date.now()) - new Date(from).getTime()) / 1000 : null

export const STATUS_LABEL: Record<IncidentStatus, string> = {
  ALERT_RECEIVED: "Alert received",
  MITIGATING: "Stopping the bleeding",
  DIAGNOSING: "Diagnosing",
  CORRELATING: "Finding the cause",
  PATCHING: "Agent fixing",
  TESTING_IN_SANDBOX: "Testing in sandbox",
  PR_CREATED: "PR open",
  UPDATING_PR: "Repairing PR",
  AWAITING_APPROVAL: "Waiting for approval",
  READY_TO_MERGE: "Ready to merge",
  RESOLVED: "Resolved",
  ESCALATED: "Escalated",
}

export const STATUS_TONE: Record<IncidentStatus, "active" | "done" | "failed" | "waiting"> = {
  ALERT_RECEIVED: "active",
  MITIGATING: "active",
  DIAGNOSING: "active",
  CORRELATING: "active",
  PATCHING: "active",
  TESTING_IN_SANDBOX: "active",
  PR_CREATED: "active",
  UPDATING_PR: "active",
  AWAITING_APPROVAL: "waiting",
  READY_TO_MERGE: "waiting",
  RESOLVED: "done",
  ESCALATED: "failed",
}

export const TONE_CLASSES = {
  active: "tint-warning",
  done: "tint-success",
  failed: "tint-danger",
  waiting: "tint-info",
  pending: "tint-muted",
}
