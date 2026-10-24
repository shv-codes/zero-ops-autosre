import React from "react"
import { AlertTriangle, Database } from "lucide-react"
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { PanelHeader } from "@/components/Panel"
import { clock } from "@/lib/format"
import type { ConnectionHistoryPoint, ConnectionTelemetry } from "@/types/api"

interface Props {
  history: ConnectionHistoryPoint[]
  current?: ConnectionTelemetry
  error?: string
  threshold: number
}

// Chart colours come from theme tokens, so they adapt to light and dark mode.
const C = {
  stuck: "hsl(var(--chart-stuck))",
  active: "hsl(var(--chart-active))",
  idle: "hsl(var(--chart-idle))",
  axis: "hsl(var(--muted-foreground))",
  grid: "hsl(var(--border))",
  danger: "hsl(var(--danger))",
}

// Legend display order (critical metrics first)
const LEGEND = [
  { key: "idle_in_transaction", label: "Stuck (idle in transaction)", color: C.stuck },
  { key: "active", label: "Active", color: C.active },
  { key: "idle", label: "Idle", color: C.idle },
] as const

// Stack render order:
// 1. Idle at bottom (healthy baseline)
// 2. Active in middle (normal workload)
// 3. Stuck at top (leaked/blocked connections surge to the top in vivid RED and touch the alert line)
const STACK_AREAS = [
  { key: "idle", name: "Idle", color: C.idle, gradId: "grad-conn-idle" },
  { key: "active", name: "Active", color: C.active, gradId: "grad-conn-active" },
  { key: "idle_in_transaction", name: "Stuck (idle in transaction)", color: C.stuck, gradId: "grad-conn-stuck" },
] as const

export const ConnectionGraph: React.FC<Props> = ({ history, current, error, threshold }) => {
  const max = current?.max || history[history.length - 1]?.max || 100
  const saturated = current ? current.utilization >= threshold : false
  const data = history.map((p) => ({ ...p, time: clock(p.timestamp) }))

  return (
    <Card className="flex h-[360px] flex-col sm:h-[420px]">
      <PanelHeader
        icon={Database}
        title="PostgreSQL connections"
        description={current ? `${Math.round(current.utilization * 100)}% of capacity` : "Telemetry unavailable"}
        actions={current ? (
          <>
            {saturated && (
              <Badge variant="destructive"><AlertTriangle className="h-3 w-3" /> Exhausting</Badge>
            )}
            <Badge variant="outline" className="font-mono tabular-nums">{current.total} / {current.max}</Badge>
          </>
        ) : <Badge variant="warning">Unavailable</Badge>}
      />
      <CardContent className="flex min-h-0 flex-1 flex-col p-4">
        {error && !current && <p className="mb-2 line-clamp-2 text-xs text-warning">{error}</p>}
        <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {LEGEND.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
        <div className="min-h-0 flex-1">
          {data.length === 0 ? (
            <div className="flex h-full items-center justify-center rounded-md border border-dashed text-center text-xs text-muted-foreground">
              No samples yet. The monitor records one every few seconds.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%" minHeight={220}>
              <AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                <defs>
                  <linearGradient id="grad-conn-idle" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={C.idle} stopOpacity={0.4} />
                    <stop offset="95%" stopColor={C.idle} stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="grad-conn-active" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={C.active} stopOpacity={0.5} />
                    <stop offset="95%" stopColor={C.active} stopOpacity={0.05} />
                  </linearGradient>
                  <linearGradient id="grad-conn-stuck" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={C.stuck} stopOpacity={0.7} />
                    <stop offset="95%" stopColor={C.stuck} stopOpacity={0.08} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke={C.grid} strokeDasharray="3 3" />
                <XAxis dataKey="time" tick={{ fontSize: 10, fill: C.axis }} tickLine={false} axisLine={false} minTickGap={48} />
                <YAxis domain={[0, max]} tick={{ fontSize: 10, fill: C.axis }} tickLine={false} axisLine={false} width={40} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null
                    const pt = payload[0]?.payload as ConnectionHistoryPoint & { time: string }
                    if (!pt) return null
                    const total = pt.total ?? (pt.idle + pt.active + pt.idle_in_transaction)
                    const limit = pt.max || max
                    const isAlert = total / limit >= threshold
                    return (
                      <div className="min-w-[190px] rounded-lg border bg-popover/95 p-2.5 text-xs text-popover-foreground shadow-lg backdrop-blur-sm">
                        <div className="mb-2 flex items-center justify-between border-b pb-1.5">
                          <span className="font-mono text-muted-foreground">{label}</span>
                          {isAlert && (
                            <Badge variant="destructive" className="h-4 px-1 text-[9px]">
                              Alert
                            </Badge>
                          )}
                        </div>
                        <div className="space-y-1.5">
                          <div className="flex items-center justify-between gap-4">
                            <span className="flex items-center gap-1.5 text-muted-foreground">
                              <span className="h-2 w-2 rounded-sm" style={{ background: C.stuck }} />
                              Stuck
                            </span>
                            <span className="font-mono font-semibold text-foreground">
                              {pt.idle_in_transaction}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4">
                            <span className="flex items-center gap-1.5 text-muted-foreground">
                              <span className="h-2 w-2 rounded-sm" style={{ background: C.active }} />
                              Active
                            </span>
                            <span className="font-mono font-semibold text-foreground">
                              {pt.active}
                            </span>
                          </div>
                          <div className="flex items-center justify-between gap-4">
                            <span className="flex items-center gap-1.5 text-muted-foreground">
                              <span className="h-2 w-2 rounded-sm" style={{ background: C.idle }} />
                              Idle
                            </span>
                            <span className="font-mono font-semibold text-foreground">
                              {pt.idle}
                            </span>
                          </div>
                          <div className="mt-2 flex items-center justify-between border-t pt-1.5 font-medium text-muted-foreground">
                            <span>Total</span>
                            <span className="font-mono font-bold text-foreground">
                              {total} <span className="font-normal text-muted-foreground">/ {limit}</span>
                            </span>
                          </div>
                        </div>
                      </div>
                    )
                  }}
                />
                <ReferenceLine
                  y={Math.round(max * threshold)}
                  stroke={C.danger}
                  strokeDasharray="4 4"
                  strokeOpacity={0.8}
                  label={{
                    value: `Alert ${Math.round(threshold * 100)}%`,
                    fill: C.danger,
                    fontSize: 10,
                    position: "insideTopRight",
                  }}
                />
                {STACK_AREAS.map((s) => (
                  <Area
                    key={s.key}
                    type="monotone"
                    dataKey={s.key}
                    name={s.name}
                    stackId="1"
                    stroke={s.color}
                    fill={`url(#${s.gradId})`}
                    strokeWidth={1.75}
                    isAnimationActive={false}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
