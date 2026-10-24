import React, { useEffect, useState } from "react"
import { Activity, AlertTriangle, Bot, Box, Database, GitPullRequest, ShieldCheck, SlidersHorizontal } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ModeToggle } from "@/components/ModeToggle"
import { cn } from "@/lib/utils"
import type { Incident, SystemStatus } from "@/types/api"

interface HeaderProps {
  system?: SystemStatus
  backendError?: string
  incident?: Incident
  onOpenControls: () => void
}

interface StatusItem {
  key: string
  ok: boolean | null
  icon: React.ElementType
  label: string
  detail?: string
}

function statusItems(system: SystemStatus): StatusItem[] {
  const cachedChecks = system.sandbox.engine === "cached"
  return [
    { key: "db", ok: system.database.reachable, icon: Database,
      label: system.database.reachable ? "Database" : "Database unreachable",
      detail: system.database.error || `${system.database.engine} @ ${system.database.host}` },
    { key: "sandbox", ok: cachedChecks ? true : system.sandbox.isolated, icon: Box,
      label: cachedChecks ? "Cached checks" : system.sandbox.isolated ? "Docker sandbox" : "Sandbox not isolated",
      detail: cachedChecks ? "Replaying recorded check results" : `Engine: ${system.sandbox.engine}` },
    { key: "llm", ok: system.mode !== "live" || system.llm.configured, icon: Bot,
      label: system.mode === "live" ? `${system.llm.provider}${system.llm.configured ? "" : " (no key)"}` : "Cached brain",
      detail: system.llm.model },
    { key: "delivery", ok: system.delivery.configured, icon: GitPullRequest,
      label: system.delivery.provider === "github" ? "GitHub" : "Local origin", detail: system.delivery.target },
  ]
}

const Dot: React.FC<{ ok: boolean | null }> = ({ ok }) => (
  <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", ok === null ? "bg-muted-foreground" : ok ? "bg-success" : "bg-warning")} />
)

export const Header: React.FC<HeaderProps> = ({ system, backendError, incident, onOpenControls }) => {
  // FR-9.3: always say when the run is not fully live or not fully isolated.
  const cachedChecks = system?.sandbox.engine === "cached"
  const banners: string[] = []
  if (backendError) banners.push(backendError)
  if (incident?.mode === "replay") banners.push(`Replay: ${incident.id} is a playback of a recorded run. Nothing is executed.`)
  else if (incident?.llm?.fallback_used) banners.push(`LLM unreachable (${incident.llm.fallback_reason}). This incident used cached recorded decisions.`)
  else if (system?.mode === "cached" && !cachedChecks) banners.push("Cached mode: the agent replays recorded decisions; files, guardrails and the sandbox still run for real.")
  if (system && !cachedChecks && !system.sandbox.isolated) banners.push("Docker is not running, so sandbox runs are not isolated (subprocess fallback).")

  const items = system ? statusItems(system) : []
  const degraded = items.some((i) => i.ok === false)

  const signature = banners.join("\u0000")
  const [open, setOpen] = useState(banners.length > 0)

  useEffect(() => {
    if (!signature) {
      setOpen(false)
      return
    }
    setOpen(true)
    const timer = window.setTimeout(() => setOpen(false), 2000)
    return () => window.clearTimeout(timer)
  }, [signature])

  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className={`grid transition-[grid-template-rows,opacity] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
        <div className="overflow-hidden">
          {banners.map((b) => (
            <div key={b} role="status" className="flex items-start gap-2 border-b border-warning/20 bg-warning/[0.07] px-4 py-1.5 text-xs text-warning sm:px-6">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span className="leading-snug">{b}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="flex h-14 items-center justify-between gap-3 px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <ShieldCheck className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-semibold tracking-tight">AutoSRE</h1>
              <span className="hidden text-xs text-muted-foreground sm:inline">/ Team Zero-Ops</span>
            </div>
            <p className="hidden truncate text-xs text-muted-foreground lg:block">
              Detect, mitigate, fix, verify and deliver. Humans merge.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 sm:gap-2">
          {/* Desktop: inline status */}
          <div className="hidden items-center gap-1 xl:flex">
            {items.map((item) => (
              <Tooltip key={item.key}>
                <TooltipTrigger asChild>
                  <span className="flex cursor-default items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
                    <Dot ok={item.ok} />
                    {item.label}
                  </span>
                </TooltipTrigger>
                {item.detail && <TooltipContent>{item.detail}</TooltipContent>}
              </Tooltip>
            ))}
          </div>

          {/* Tablet / mobile: compact status menu */}
          {system && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="gap-1.5 px-2 xl:hidden" aria-label="System status">
                  <Activity className={cn(degraded ? "text-warning" : "text-success")} />
                  <span className="hidden text-xs sm:inline">Status</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel>System status</DropdownMenuLabel>
                {items.map((item) => (
                  <DropdownMenuItem key={item.key} className="items-start" onSelect={(e) => e.preventDefault()}>
                    <item.icon className="mt-0.5 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 text-sm"><Dot ok={item.ok} />{item.label}</div>
                      {item.detail && <div className="truncate text-xs text-muted-foreground">{item.detail}</div>}
                    </div>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          {system && (
            <Badge variant={system.mode === "live" ? "success" : "warning"} className="font-mono uppercase tracking-wide">
              {system.mode}
            </Badge>
          )}
          <ModeToggle />
          <Button onClick={onOpenControls} size="sm" className="px-2.5 sm:px-3" aria-label="Open controls">
            <SlidersHorizontal />
            <span className="hidden sm:inline">Controls</span>
          </Button>
        </div>
      </div>
    </header>
  )
}
