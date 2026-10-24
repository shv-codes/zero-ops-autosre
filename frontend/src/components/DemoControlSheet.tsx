import React, { useState } from "react"
import { toast } from "sonner"
import { Film, Github, OctagonX, Play, Radio, RotateCcw, Trash2 } from "lucide-react"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  useConfig, useGitHubDisconnect, useGitHubStatus, usePrototype, useReplay, useReset, useTraffic, useTriggerDemo, useUpdateConfig,
} from "@/hooks/useAutoSRE"
import { api } from "@/lib/api"
import type { IncidentStatus, RunMode, SystemStatus } from "@/types/api"

interface Props {
  open: boolean
  onClose: () => void
  system?: SystemStatus
  incidentId?: string
  incidentStatus?: IncidentStatus
  onForceStop: () => void
  onDelete: () => void
  stopping?: boolean
  deleting?: boolean
  onIncidentCreated: (id: string) => void
}

const err = (e: unknown) => toast.error((e as Error).message)

const Section: React.FC<{ title: string; description?: React.ReactNode; children: React.ReactNode }> = ({ title, description, children }) => (
  <section className="space-y-3">
    <div>
      <h3 className="text-sm font-medium">{title}</h3>
      {description && <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>}
    </div>
    {children}
  </section>
)

const Field: React.FC<{ id: string; label: string; hint?: string; children: React.ReactNode }> = ({ id, label, hint, children }) => (
  <div className="space-y-1.5">
    <Label htmlFor={id}>{label}</Label>
    {children}
    {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
  </div>
)

const Range: React.FC<{ id: string; min: number; max: number; value: number; onCommit: (v: number) => void }> = ({ id, min, max, value, onCommit }) => (
  <input id={id} type="range" min={min} max={max} defaultValue={value} key={value}
         className="h-2 w-full cursor-pointer accent-[hsl(var(--primary))]"
         onPointerUp={(e) => onCommit(Number((e.target as HTMLInputElement).value))}
         onKeyUp={(e) => onCommit(Number((e.target as HTMLInputElement).value))} />
)

export const DemoControlSheet: React.FC<Props> = ({
  open, onClose, system, incidentId, incidentStatus, onForceStop, onDelete, stopping, deleting, onIncidentCreated,
}) => {
  const config = useConfig().data
  const traffic = useTraffic().data
  const update = useUpdateConfig()
  const play = usePrototype()
  const trigger = useTriggerDemo()
  const replay = useReplay()
  const reset = useReset()
  const github = useGitHubStatus().data
  const disconnect = useGitHubDisconnect()
  const [clear, setClear] = useState(true)
  const [reseed, setReseed] = useState(false)

  const set = (patch: Parameters<typeof update.mutate>[0]) =>
    update.mutate(patch, { onSuccess: () => toast.success("Settings saved"), onError: err })
  const finished = incidentStatus === "RESOLVED" || incidentStatus === "ESCALATED"

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="scrollbar-thin w-full space-y-6 overflow-y-auto p-5 sm:max-w-md sm:p-6">
        <SheetHeader className="space-y-1 text-left">
          <SheetTitle>Controls</SheetTitle>
          <SheetDescription className="text-xs">
            These simulate the outside world (users, a teammate, a reviewer). They never let AutoSRE skip a safety rule.
          </SheetDescription>
        </SheetHeader>

        <Section title="Play the prototype"
                 description="No Docker needed. Cached checks find the leak and open a pull request, then a real commit on main creates a merge conflict that AutoSRE resolves.">
          <Button className="w-full" disabled={play.isPending}
                  onClick={() => play.mutate(undefined, {
                    onSuccess: (r) => {
                      onIncidentCreated(r.incident.id)
                      toast.success("Prototype playing", { description: r.message })
                      onClose()
                    },
                    onError: err,
                  })}>
            <Play /> {play.isPending ? "Starting…" : "Play prototype"}
          </Button>
        </Section>

        <Separator />

        <Section title="Live incident"
                 description={<>Sends real HTTP traffic to the victim service ({system?.victim.base_url}). The monitor raises the alert on its own.</>}>
          <div className="grid gap-2">
            <Button variant="outline" disabled={trigger.isPending || traffic?.running}
                    onClick={() => trigger.mutate(undefined, { onSuccess: (r) => toast.info(r.message), onError: err })}>
              <Radio /> {traffic?.running ? `Traffic running… ${traffic.sent}/${traffic.target}` : "Start incident"}
            </Button>
            {traffic && traffic.sent > 0 && (
              <p className="font-mono text-xs tabular-nums text-muted-foreground">sent {traffic.sent} · ok {traffic.ok} · errors {traffic.errors}</p>
            )}
            <Button variant="ghost" disabled={replay.isPending}
                    onClick={() => replay.mutate(undefined, {
                      onSuccess: (r) => { onIncidentCreated(r.incident.id); toast.info("Replaying a recorded run"); onClose() },
                      onError: err,
                    })}>
              <Film /> Replay recorded run
            </Button>
          </div>
        </Section>

        <Separator />

        <Section title="Agent settings" description="Applies to new incidents.">
          <Field id="mode" label="Mode">
            <Select value={config?.mode} onValueChange={(v) => set({ mode: v as RunMode })}>
              <SelectTrigger id="mode"><SelectValue placeholder="Mode" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="cached">Cached: recorded decisions, real tools</SelectItem>
                <SelectItem value="live">Live: real LLM</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field id="oversight" label="Human oversight">
            <Select value={config?.approval_mode} onValueChange={(v) => set({ approval_mode: v as "autonomous" | "review" })}>
              <SelectTrigger id="oversight"><SelectValue placeholder="Oversight" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="autonomous">Autonomous: act, then report</SelectItem>
                <SelectItem value="review">Review: ask before acting</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field id="provider" label="LLM provider" hint="Used in live mode.">
            <Select value={config?.llm_provider} onValueChange={(v) => set({ llm_provider: v })}>
              <SelectTrigger id="provider"><SelectValue placeholder="Provider" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="groq">Groq</SelectItem>
                <SelectItem value="nvidia">NVIDIA (Nemotron)</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field id="attempts" label={`Max fix attempts: ${config?.max_attempts ?? 3}`}>
            <Range id="attempts" min={1} max={5} value={config?.max_attempts || 3} onCommit={(v) => set({ max_attempts: v })} />
          </Field>
          <Field id="threshold" label={`Alert threshold: ${Math.round((config?.alert_threshold || 0.9) * 100)}%`}>
            <Range id="threshold" min={50} max={100} value={Math.round((config?.alert_threshold || 0.9) * 100)}
                   onCommit={(v) => set({ alert_threshold: v / 100 })} />
          </Field>
        </Section>

        <Separator />

        <Section title="GitHub">
          {!github || github.provider === "local" ? (
            <p className="text-xs text-muted-foreground">Using the local "pretend GitHub" (DELIVERY_PROVIDER=local). See docs/GITHUB_APP_SETUP.md for real PRs.</p>
          ) : github.connected ? (
            <div className="space-y-2 rounded-lg border p-3 text-xs">
              <p className="flex items-center gap-1.5 font-medium"><span className="h-1.5 w-1.5 rounded-full bg-success" />
                Connected to {github.repo}{github.app ? ` as ${github.app.bot_login}` : " (personal token)"}</p>
              {github.token_expires_in_seconds !== null && (
                <p className="text-muted-foreground">Token renews automatically (expires in {Math.round(github.token_expires_in_seconds / 60)} min).</p>
              )}
              {github.auth_mode === "app" && (
                <Button size="sm" variant="outline" disabled={disconnect.isPending}
                        onClick={() => disconnect.mutate(undefined, { onSuccess: (r) => toast.info(r.note), onError: err })}>
                  Disconnect
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {github.error && <p className="text-xs text-warning">{github.error}</p>}
              {github.auth_mode === "app" && (
                <Button asChild className="w-full"><a href={api.githubConnectUrl}><Github /> Connect GitHub</a></Button>
              )}
            </div>
          )}
        </Section>

        <Separator />

        <Section title="This incident"
                 description={incidentId ? <><span className="font-mono">{incidentId}</span>. Force stop ends the agent now. Delete removes its history.</> : "Select an incident first."}>
          <div className="grid grid-cols-2 gap-2">
            <Button variant="outline" disabled={!incidentId || stopping || finished} onClick={onForceStop}>
              <OctagonX /> {stopping ? "Stopping…" : "Force stop"}
            </Button>
            <Button variant="outline" className="text-danger hover:bg-danger/10 hover:text-danger"
                    disabled={!incidentId || deleting} onClick={onDelete}>
              <Trash2 /> {deleting ? "Deleting…" : "Delete"}
            </Button>
          </div>
        </Section>

        <Separator />

        <Section title="Reset environment">
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="clear" className="font-normal">Clear incident history</Label>
              <Switch id="clear" checked={clear} onCheckedChange={setClear} />
            </div>
            <div className="flex items-center justify-between gap-3">
              <Label htmlFor="reseed" className="font-normal">Re-seed the victim repo (undo merged fixes)</Label>
              <Switch id="reseed" checked={reseed} onCheckedChange={setReseed} />
            </div>
          </div>
          <Button variant="outline" className="w-full" disabled={reset.isPending}
                  onClick={() => reset.mutate({ clear_incidents: clear, reseed_repo: reseed }, {
                    onSuccess: () => { toast.success("Environment reset"); onClose() }, onError: err,
                  })}>
            <RotateCcw /> Stop traffic & reset
          </Button>
        </Section>
      </SheetContent>
    </Sheet>
  )
}
