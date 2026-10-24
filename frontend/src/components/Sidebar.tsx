import React, { useState } from "react"
import { Activity, ChevronRight, Square, Trash2 } from "lucide-react"
import { isActive } from "@/hooks/useAutoSRE"
import { clock, STATUS_LABEL, STATUS_TONE, TONE_CLASSES } from "@/lib/format"
import type { IncidentSummary } from "@/types/api"

interface Props {
  incidents: IncidentSummary[]
  selectedId?: string
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onStop: (id: string) => void
  busy?: boolean
}

const ICON_BUTTON =
  "flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors disabled:opacity-40 md:h-6 md:w-6 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"

const EASE = "duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]"

export const Sidebar: React.FC<Props> = ({ incidents, selectedId, onSelect, onDelete, onStop, busy }) => {
  const [open, setOpen] = useState(false)
  const toggle = () => setOpen((value) => !value)

  return (
    <div className="relative w-full shrink-0 self-start md:sticky md:top-28 md:w-auto">
      <aside
        className={`overflow-x-hidden border-b bg-background transition-[width] md:border-b-0 md:border-r motion-reduce:transition-none ${EASE} ${
          open
            ? "w-full md:w-64 md:max-h-[calc(100dvh-7rem)] md:overflow-y-auto"
            : "w-full overflow-y-hidden md:w-12"
        }`}
      >
        <div className="w-full md:w-64">
          <button
            type="button"
            tabIndex={-1}
            aria-hidden
            onClick={toggle}
            className="flex h-12 w-full items-center gap-2.5 px-4 text-left text-muted-foreground hover:text-foreground"
          >
            <Activity className="h-4 w-4 shrink-0" />
            <span className={`truncate text-sm font-medium text-foreground transition-opacity motion-reduce:transition-none ${EASE} ${open ? "opacity-100" : "opacity-100 md:opacity-0"}`}>
              Incidents
            </span>
            <span className={`text-[10px] font-medium tabular-nums text-muted-foreground transition-opacity motion-reduce:transition-none ${EASE} ${open ? "opacity-100" : "opacity-100 md:opacity-0"}`}>
              {incidents.length}
            </span>
          </button>

          <div className={`grid transition-[grid-template-rows] motion-reduce:transition-none ${EASE} ${open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"}`}>
            <div
              className="overflow-hidden"
              aria-hidden={!open}
              ref={(node) => {
                if (!node) return
                if (open) node.removeAttribute("inert")
                else node.setAttribute("inert", "")
              }}
            >
              <div className={`space-y-2 px-3 pb-3 transition-opacity motion-reduce:transition-none ${EASE} ${open ? "opacity-100" : "pointer-events-none opacity-0"}`}>
                {incidents.length === 0 && <p className="px-1 text-xs text-muted-foreground/70">None yet.</p>}
                {incidents.map((inc) => {
                  const running = isActive(inc.status)
                  return (
                    <div key={inc.id} role="button" tabIndex={0} onClick={() => onSelect(inc.id)}
                         onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(inc.id))}
                         aria-current={inc.id === selectedId ? "true" : undefined}
                         className={`group w-full cursor-pointer rounded-lg border p-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                           inc.id === selectedId ? "border-foreground/15 bg-accent" : "border-transparent hover:bg-accent/60"}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs font-medium">{inc.id}</span>
                        <span className="text-[11px] tabular-nums text-muted-foreground">{clock(inc.created_at)}</span>
                      </div>
                      <div className="mt-1.5 flex items-center gap-1.5">
                        <span className={`rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[STATUS_TONE[inc.status]]}`}>{STATUS_LABEL[inc.status]}</span>
                        {inc.mode !== "live" && <span className="text-[10px] uppercase text-muted-foreground">{inc.mode}</span>}
                        <div className="ml-auto flex items-center gap-0.5 opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
                          {running && (
                            <button type="button" disabled={busy} title={`Force-stop ${inc.id}`} aria-label={`Force-stop ${inc.id}`}
                                    onClick={(e) => { e.stopPropagation(); onStop(inc.id) }}
                                    className={`${ICON_BUTTON} hover:bg-warning/10 hover:text-warning`}>
                              <Square className="h-3 w-3" />
                            </button>
                          )}
                          <button type="button" disabled={busy || running} title={running ? "Stop it before deleting" : `Delete ${inc.id}`}
                                  aria-label={`Delete ${inc.id}`}
                                  onClick={(e) => { e.stopPropagation(); onDelete(inc.id) }}
                                  className={`${ICON_BUTTON} hover:bg-danger/10 hover:text-danger`}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </aside>

      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        aria-label={open ? "Collapse incidents" : "Show incidents"}
        className="absolute right-3 top-3 z-20 flex h-6 w-6 items-center justify-center rounded-full border bg-background text-muted-foreground shadow-sm transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:-right-3"
      >
        <ChevronRight className={`h-3.5 w-3.5 transition-transform motion-reduce:transition-none ${EASE} ${open ? "rotate-180" : ""}`} />
      </button>

      {!open && (
        <span className="pointer-events-none absolute left-6 top-2 hidden h-4 min-w-4 items-center justify-center rounded-full bg-muted px-1 text-[9px] font-medium tabular-nums text-foreground/80 ring-1 ring-background md:flex">
          {incidents.length}
        </span>
      )}
    </div>
  )
}
