import React, { useEffect, useRef, useState } from "react"
import { toast, Toaster } from "sonner"
import { Header } from "@/components/Header"
import { Sidebar } from "@/components/Sidebar"
import { PipelineStepper } from "@/components/PipelineStepper"
import { LiveTerminal } from "@/components/LiveTerminal"
import { ConnectionGraph } from "@/components/ConnectionGraph"
import { MttrCard } from "@/components/MttrCard"
import { SuspectCard } from "@/components/SuspectCard"
import { PrCard } from "@/components/PrCard"
import { ReviewPanel } from "@/components/ReviewPanel"
import { DetailTabs } from "@/components/DetailTabs"
import { GuardrailsPanel } from "@/components/GuardrailsPanel"
import { DemoControlSheet } from "@/components/DemoControlSheet"
import { ApprovalCard } from "@/components/ApprovalCard"
import { ConfirmDialog } from "@/components/ConfirmDialog"
import { useTheme } from "@/components/theme-provider"
import {
  isActive, useConfig, useDeleteIncident, useForceStop, useGuardrails, useIncident, useIncidents, useSystem, useTelemetry, useTelemetryHistory, useTimeline,
} from "@/hooks/useAutoSRE"
import { STATUS_LABEL } from "@/lib/format"

export const Dashboard: React.FC = () => {
  const [selectedId, setSelectedId] = useState<string>()
  const [controlsOpen, setControlsOpen] = useState(false)
  const pinned = useRef(false)

  const { resolved: resolvedTheme } = useTheme()
  const system = useSystem()
  const incidents = useIncidents()
  const incident = useIncident(selectedId).data
  const telemetry = useTelemetry()
  const history = useTelemetryHistory().data || []
  const config = useConfig().data
  const guardrails = useGuardrails(selectedId, isActive(incident?.status)).data?.checks || []
  const timeline = useTimeline(selectedId, incident?.timeline)
  const forceStop = useForceStop()
  const deleteIncident = useDeleteIncident()

  // Destructive actions go through a confirmation modal first.
  const [pending, setPending] = useState<{ kind: "delete" | "stop"; id: string } | null>(null)
  const stopIncident = (id: string) => setPending({ kind: "stop", id })
  const removeIncident = (id: string) => setPending({ kind: "delete", id })
  const confirmPending = () => {
    if (!pending) return
    const { kind, id } = pending
    const done = { onSettled: () => setPending(null), onError: (e: unknown) => toast.error((e as Error).message) }
    if (kind === "stop") {
      forceStop.mutate(id, { ...done, onSuccess: () => toast.success(`${id} force-stopped`) })
      return
    }
    deleteIncident.mutate(id, {
      ...done,
      onSuccess: () => {
        if (id === selectedId) {
          pinned.current = false
          setSelectedId(undefined)
        }
        toast.success(`${id} deleted`)
      },
    })
  }
  const stopSelected = () => selectedId && stopIncident(selectedId)
  const deleteSelected = () => selectedId && removeIncident(selectedId)

  // Coming back from GitHub's install page: ?github=connected | ?github=error&reason=...
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const result = params.get("github")
    if (!result) return
    if (result === "connected") toast.success("GitHub connected", { description: "AutoSRE can now open pull requests as its bot." })
    else toast.error("GitHub connection failed", { description: params.get("reason") || undefined })
    window.history.replaceState({}, "", window.location.pathname)
  }, [])

  // Follow the newest incident unless the user picked one.
  useEffect(() => {
    const newest = incidents.data?.[0]?.id
    if (newest && (!pinned.current || !selectedId)) setSelectedId(newest)
  }, [incidents.data?.[0]?.id])

  // Toast on important transitions.
  const lastStatus = useRef<string>()
  useEffect(() => {
    if (!incident) return
    if (lastStatus.current && lastStatus.current !== incident.status) {
      const label = STATUS_LABEL[incident.status]
      if (incident.status === "ESCALATED") toast.error(`${incident.id}: escalated to a human`, { description: incident.escalation_reason })
      else if (["PR_CREATED", "READY_TO_MERGE", "RESOLVED", "UPDATING_PR"].includes(incident.status)) toast.info(`${incident.id}: ${label}`)
    }
    lastStatus.current = incident.status
  }, [incident?.status])

  const backendError = system.error ? (system.error as Error).message : undefined

  return (
    <div className="flex min-h-screen flex-col bg-muted/30 text-foreground dark:bg-background">
      <Toaster position="bottom-right" theme={resolvedTheme} richColors closeButton
               toastOptions={{ className: "font-sans" }} />
      <Header system={system.data} backendError={backendError} incident={incident} onOpenControls={() => setControlsOpen(true)} />
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <Sidebar incidents={incidents.data || []} selectedId={selectedId}
                 onSelect={(id) => { pinned.current = true; setSelectedId(id) }}
                 onDelete={removeIncident} onStop={stopIncident}
                 busy={deleteIncident.isPending || forceStop.isPending} />
        <main className="mx-auto w-full min-w-0 max-w-[1600px] flex-1 space-y-4 p-3 sm:space-y-6 sm:p-4 lg:p-6">
          <PipelineStepper incident={incident} onForceStop={stopSelected} onDelete={deleteSelected}
                           stopping={forceStop.isPending} deleting={deleteIncident.isPending} />
          <ApprovalCard incident={incident} />
          <div className="grid grid-cols-1 gap-4 sm:gap-6 xl:grid-cols-2">
            <LiveTerminal timeline={timeline} />
            <ConnectionGraph history={history} current={telemetry.data}
                             error={telemetry.error ? (telemetry.error as Error).message : undefined}
                             threshold={config?.alert_threshold || 0.9} />
          </div>
          <div className="grid grid-cols-1 gap-4 sm:gap-6 md:grid-cols-2 xl:grid-cols-3">
            <MttrCard incident={incident} />
            <SuspectCard incident={incident} />
            <PrCard incident={incident} />
          </div>
          <ReviewPanel incident={incident} />
          <div className="grid grid-cols-1 gap-4 sm:gap-6 xl:grid-cols-3">
            <div className="xl:col-span-2"><DetailTabs incident={incident} /></div>
            <GuardrailsPanel checks={guardrails} />
          </div>
        </main>
      </div>
      <DemoControlSheet open={controlsOpen} onClose={() => setControlsOpen(false)} system={system.data}
                        incidentId={selectedId} incidentStatus={incident?.status}
                        onForceStop={stopSelected} onDelete={deleteSelected}
                        stopping={forceStop.isPending} deleting={deleteIncident.isPending}
                        onIncidentCreated={(id) => { pinned.current = false; setSelectedId(id) }} />
      <ConfirmDialog
        open={!!pending}
        tone={pending?.kind === "stop" ? "warning" : "danger"}
        title={pending?.kind === "stop" ? `Force-stop ${pending.id}?` : `Delete ${pending?.id}?`}
        description={pending?.kind === "stop"
          ? <>The agent stops immediately and the incident is marked <strong className="text-foreground">escalated</strong> for a human to take over.</>
          : <>This permanently removes the incident, its timeline, agent steps, sandbox runs and <strong className="text-foreground">audit trail</strong>. This can't be undone. Export the audit JSON first if you need it.</>}
        confirmLabel={pending?.kind === "stop" ? "Force-stop" : "Delete incident"}
        busy={deleteIncident.isPending || forceStop.isPending}
        onConfirm={confirmPending}
        onCancel={() => setPending(null)}
      />
    </div>
  )
}
