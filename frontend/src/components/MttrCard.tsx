import React, { useEffect, useState } from "react"
import { Timer } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { PanelHeader } from "@/components/Panel"
import { duration, secondsBetween } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Incident } from "@/types/api"

const MANUAL_MTTR_SECONDS = 45 * 60 // typical manual response, for comparison (AO-1)

const Stat: React.FC<{ label: string; value: string; tone?: string; big?: boolean }> = ({ label, value, tone, big }) => (
  <div>
    <div className="text-xs text-muted-foreground">{label}</div>
    <div className={cn("mt-0.5 font-semibold tabular-nums tracking-tight", big ? "text-2xl" : "text-lg", tone)}>{value}</div>
  </div>
)

export const MttrCard: React.FC<{ incident?: Incident }> = ({ incident }) => {
  const [, tick] = useState(0)
  const running = !!incident && !incident.ready_at && !incident.finished_at
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [running])

  const toFix = incident ? (incident.mttr_seconds ?? secondsBetween(incident.created_at, null)) : null
  const toMitigate = incident?.time_to_mitigate_seconds ?? null
  const pct = toFix ? Math.min(100, (toFix / MANUAL_MTTR_SECONDS) * 100) : 0
  const speedup = toFix ? Math.max(1, Math.round(MANUAL_MTTR_SECONDS / Math.max(toFix, 1))) : null

  return (
    <Card>
      <PanelHeader icon={Timer} title="Time to recovery" description={running ? "Running" : "Alert to verified fix"} />
      <CardContent className="space-y-4 p-4">
        {!incident ? (
          <p className="text-sm text-muted-foreground">Starts when an alert arrives.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4">
              <Stat label="Service restored" value={toMitigate !== null ? duration(toMitigate) : running ? "…" : "—"} />
              <Stat label="Fix ready to merge" value={duration(toFix)} big
                    tone={incident.status === "ESCALATED" ? "text-danger" : undefined} />
            </div>
            <div className="space-y-1.5">
              <div className="flex justify-between gap-2 text-xs text-muted-foreground">
                <span>vs. typical manual response (≈45 min)</span>
                {speedup && incident.status !== "ESCALATED" && <span className="shrink-0 font-medium text-success">{speedup}× faster</span>}
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-success transition-all" style={{ width: `${Math.max(pct, 1)}%` }} />
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
