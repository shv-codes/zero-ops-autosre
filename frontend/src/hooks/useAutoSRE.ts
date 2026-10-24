import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { api, subscribeTimeline } from "@/lib/api"
import type { IncidentStatus, SystemConfig, TimelineEntry } from "@/types/api"

const ACTIVE: IncidentStatus[] = [
  "ALERT_RECEIVED", "MITIGATING", "DIAGNOSING", "CORRELATING", "PATCHING", "TESTING_IN_SANDBOX", "PR_CREATED", "UPDATING_PR", "AWAITING_APPROVAL",
]
export const isActive = (s?: IncidentStatus) => !!s && ACTIVE.includes(s)

export const useSystem = () => useQuery({ queryKey: ["system"], queryFn: api.system, refetchInterval: 10000 })

export const useIncidents = () => useQuery({ queryKey: ["incidents"], queryFn: api.incidents, refetchInterval: 3000 })

export function useIncident(id?: string) {
  return useQuery({
    queryKey: ["incident", id],
    queryFn: () => api.incident(id!),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && !["RESOLVED", "ESCALATED"].includes(q.state.data.status) ? 1500 : 10000),
  })
}

const detailOpts = (id: string | undefined, active: boolean) => ({ enabled: !!id, refetchInterval: active ? 2500 : false as const })

export const useDiff = (id?: string, active = false) =>
  useQuery({ queryKey: ["diff", id], queryFn: () => api.diff(id!), ...detailOpts(id, active) })
export const usePostmortem = (id?: string, active = false) =>
  useQuery({ queryKey: ["postmortem", id], queryFn: () => api.postmortem(id!), ...detailOpts(id, active) })
export const useSteps = (id?: string, active = false) =>
  useQuery({ queryKey: ["steps", id], queryFn: () => api.steps(id!), ...detailOpts(id, active) })
export const useSandboxRuns = (id?: string, active = false) =>
  useQuery({ queryKey: ["sandbox", id], queryFn: () => api.sandboxRuns(id!), ...detailOpts(id, active) })
export const useGuardrails = (id?: string, active = false) =>
  useQuery({ queryKey: ["guardrails", id], queryFn: () => api.guardrails(id), refetchInterval: active ? 2000 : 10000 })

export const useTelemetry = () =>
  useQuery({ queryKey: ["telemetry"], queryFn: api.telemetry, refetchInterval: 2000, retry: false })
export const useTelemetryHistory = () =>
  useQuery({ queryKey: ["telemetry-history"], queryFn: () => api.telemetryHistory(10), refetchInterval: 2000 })
export const useTraffic = () => useQuery({ queryKey: ["traffic"], queryFn: api.traffic, refetchInterval: 2000 })
export const useGitHubStatus = () => useQuery({ queryKey: ["github"], queryFn: api.githubStatus, refetchInterval: 30000 })
export const useGitHubDisconnect = () => useInvalidatingMutation(() => api.githubDisconnect(), [["github"], ["system"]])
export const useConfig = () => useQuery({ queryKey: ["config"], queryFn: api.config })

function useInvalidatingMutation<TArgs, TResult>(fn: (args: TArgs) => Promise<TResult>, keys: string[][]) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => keys.forEach((k) => qc.invalidateQueries({ queryKey: k })),
  })
}

export const useUpdateConfig = () =>
  useInvalidatingMutation((patch: Partial<SystemConfig>) => api.updateConfig(patch), [["config"], ["system"]])
export const usePrototype = () => useInvalidatingMutation(() => api.prototype(), [["incidents"]])
export const useTriggerDemo = () => useInvalidatingMutation(() => api.triggerDemo(), [["traffic"]])
export const useReplay = () => useInvalidatingMutation(() => api.replay(), [["incidents"]])
export const useTeammatePush = () => useInvalidatingMutation(() => api.teammatePush(), [["incidents"]])
export const useDecide = () =>
  useInvalidatingMutation(
    (a: { id: string; gate: string; decision: "approve" | "deny"; by?: string; note?: string }) =>
      api.decide(a.id, { gate: a.gate, decision: a.decision, by: a.by, note: a.note }),
    [["incident"], ["incidents"]],
  )
export const useMerge = () => useInvalidatingMutation((id: string) => api.merge(id), [["incidents"], ["incident"]])
export const useForceStop = () => useInvalidatingMutation((id: string) => api.forceStop(id), [["incidents"], ["incident"]])
export const useDeleteIncident = () => useInvalidatingMutation((id: string) => api.deleteIncident(id), [["incidents"], ["incident"]])
export const useReset = () =>
  useInvalidatingMutation(
    (opts: { clear_incidents?: boolean; reseed_repo?: boolean }) => api.reset(opts),
    [["incidents"], ["incident"], ["telemetry-history"], ["traffic"]],
  )

/** Timeline: initial rows from the incident, then live SSE events (deduplicated by id). */
export function useTimeline(incidentId: string | undefined, initial: TimelineEntry[] | undefined) {
  const [events, setEvents] = useState<TimelineEntry[]>([])
  const seen = useRef<Set<number>>(new Set())

  useEffect(() => {
    seen.current = new Set()
    setEvents([])
  }, [incidentId])

  useEffect(() => {
    if (!initial?.length) return
    setEvents((prev) => {
      const merged = [...prev]
      for (const e of initial) {
        if (!seen.current.has(e.id)) {
          seen.current.add(e.id)
          merged.push(e)
        }
      }
      return merged.sort((a, b) => a.id - b.id)
    })
  }, [initial])

  useEffect(() => {
    if (!incidentId) return
    return subscribeTimeline(incidentId, {
      onEvent: (e) => {
        if (seen.current.has(e.id)) return
        seen.current.add(e.id)
        setEvents((prev) => [...prev, e])
      },
    })
  }, [incidentId])

  return events
}
