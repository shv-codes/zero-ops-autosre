import React from "react"
import { AlertCircle, Bell, Check, GitMerge, GitPullRequest, Loader2, OctagonX, Search, ShieldCheck, Siren, Trash2, Wrench } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { STATUS_LABEL, STATUS_TONE } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Incident, IncidentStatus } from "@/types/api"

type StepState = "done" | "active" | "failed" | "pending" | "waiting"

const STEPS: { id: string; label: string; icon: React.ElementType; states: IncidentStatus[] }[] = [
  { id: "alert", label: "Alert", icon: Bell, states: ["ALERT_RECEIVED"] },
  { id: "diag", label: "Diagnose", icon: Search, states: ["DIAGNOSING"] },
  { id: "mitigate", label: "Mitigate", icon: Siren, states: ["MITIGATING"] },
  { id: "corr", label: "Root cause", icon: Search, states: ["CORRELATING"] },
  { id: "patch", label: "Patch", icon: Wrench, states: ["PATCHING"] },
  { id: "test", label: "Sandbox", icon: ShieldCheck, states: ["TESTING_IN_SANDBOX"] },
  { id: "pr", label: "Pull request", icon: GitPullRequest, states: ["PR_CREATED", "UPDATING_PR"] },
  { id: "merge", label: "Merge", icon: GitMerge, states: ["READY_TO_MERGE", "RESOLVED"] },
]

function lastActiveIndex(incident: Incident): number {
  // For escalations / approvals, find the last real step reached from the timeline.
  const states = incident.timeline.map((e) => e.state).filter((s) => s !== "ESCALATED" && s !== "AWAITING_APPROVAL")
  const last = states[states.length - 1] || "ALERT_RECEIVED"
  return STEPS.findIndex((s) => s.states.includes(last))
}

function stepState(idx: number, incident: Incident): StepState {
  const status = incident.status
  const current = status === "ESCALATED" || status === "AWAITING_APPROVAL"
    ? lastActiveIndex(incident) : STEPS.findIndex((s) => s.states.includes(status))
  if (status === "ESCALATED") return idx < current ? "done" : idx === current ? "failed" : "pending"
  if (status === "RESOLVED") return "done"
  if (status === "READY_TO_MERGE") return idx < 7 ? "done" : "waiting"
  if (status === "AWAITING_APPROVAL") return idx < current ? "done" : idx === current ? "waiting" : "pending"
  // PATCHING <-> TESTING alternate during retries; treat both as the "fix" phase.
  const inFix = status === "PATCHING" || status === "TESTING_IN_SANDBOX"
  if (inFix && (idx === 4 || idx === 5)) return STEPS[idx].states.includes(status) ? "active" : incident.attempt > 0 ? "done" : "pending"
  return idx < current ? "done" : idx === current ? "active" : "pending"
}

const CIRCLE: Record<StepState, string> = {
  done: "border-success/40 bg-success/10 text-success",
  active: "border-foreground bg-foreground text-background",
  waiting: "border-info/50 bg-info/10 text-info",
  failed: "border-danger/50 bg-danger/10 text-danger",
  pending: "border-border bg-background text-muted-foreground/60",
}

const STATUS_BADGE = { active: "outline", done: "success", failed: "destructive", waiting: "info" } as const

export const PipelineStepper: React.FC<{
  incident?: Incident
  onForceStop?: () => void
  onDelete?: () => void
  stopping?: boolean
  deleting?: boolean
}> = ({ incident, onForceStop, onDelete, stopping, deleting }) => {
  if (!incident) {
    return (
      <Card className="border-dashed p-6 text-center">
        <p className="text-sm font-medium">No incident yet</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
          Open <span className="font-medium text-foreground">Controls → Start incident</span> to send traffic to the victim service.
          The monitor raises the alert by itself when connections pass the threshold.
        </p>
      </Card>
    )
  }
  const rounds = incident.pull_request?.rounds || 0
  const running = incident.status !== "RESOLVED" && incident.status !== "ESCALATED"
  const tone = STATUS_TONE[incident.status]

  return (
    <Card className="p-4 sm:p-5">
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-base font-semibold tracking-tight">{incident.id}</h2>
            <Badge variant={STATUS_BADGE[tone]}>
              {running && tone === "active" && <Loader2 className="h-3 w-3 animate-spin" />}
              {STATUS_LABEL[incident.status]}
            </Badge>
          </div>
          {incident.status === "ESCALATED" && incident.escalation_reason && (
            <p className="mt-1 text-sm text-danger">{incident.escalation_reason}</p>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant="muted" className="tabular-nums">Attempt {Math.max(incident.attempt, 0)}/{incident.max_attempts}</Badge>
            {incident.attempt > 1 && <Badge variant="warning">Self-healed with test feedback</Badge>}
            {rounds > 0 && <Badge variant="info">{rounds} PR repair round{rounds > 1 ? "s" : ""}</Badge>}
            {incident.mode !== "live" && <Badge variant="muted" className="uppercase">{incident.mode}</Badge>}
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          {running && (
            <Button variant="outline" size="sm" disabled={stopping} onClick={onForceStop} className="flex-1 sm:flex-none">
              <OctagonX /> {stopping ? "Stopping…" : "Force stop"}
            </Button>
          )}
          <Button variant="outline" size="sm" disabled={deleting} onClick={onDelete}
                  className="flex-1 text-danger hover:bg-danger/10 hover:text-danger sm:flex-none">
            <Trash2 /> {deleting ? "Deleting…" : "Delete"}
          </Button>
        </div>
      </div>

      <ol className="grid grid-cols-4 gap-y-4 lg:grid-cols-8" aria-label="Incident progress">
        {STEPS.map((step, idx) => {
          const st = stepState(idx, incident)
          const Icon = step.icon
          const next = idx < STEPS.length - 1 ? stepState(idx + 1, incident) : null
          return (
            <li key={step.id} className="relative flex flex-col items-center gap-1.5 text-center"
                aria-current={st === "active" ? "step" : undefined}>
              {next && (
                <span aria-hidden
                      className={cn("absolute left-[calc(50%+1.125rem)] right-[calc(-50%+1.125rem)] top-4 h-px",
                                    (idx + 1) % 4 === 0 && "lg:block hidden",
                                    st === "done" && next !== "pending" ? "bg-success/50" : "bg-border")} />
              )}
              <span className={cn("relative z-10 flex h-8 w-8 items-center justify-center rounded-full border", CIRCLE[st])}>
                {st === "done" ? <Check className="h-4 w-4" />
                  : st === "active" ? <Loader2 className="h-4 w-4 animate-spin" />
                  : st === "failed" ? <AlertCircle className="h-4 w-4" />
                  : <Icon className="h-3.5 w-3.5" />}
              </span>
              <span className={cn("text-[11px] leading-tight sm:text-xs",
                                  st === "pending" ? "text-muted-foreground" : "font-medium")}>{step.label}</span>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
