import React, { useState } from "react"
import { ChevronDown, Download } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Markdown } from "@/components/Markdown"
import { DiffLines } from "@/components/ReviewPanel"
import { isActive, useDiff, usePostmortem, useSandboxRuns, useSteps } from "@/hooks/useAutoSRE"
import { api } from "@/lib/api"
import { clock } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { AiCard, Incident } from "@/types/api"

const TASK_LABEL = { fix: "Fix", resolve_conflict: "Conflict", fix_ci: "CI" }

const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">{children}</p>
)

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="grid gap-1 border-b py-3 last:border-0 sm:grid-cols-[11rem_1fr] sm:gap-4">
    <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
    <dd className="text-sm">{children}</dd>
  </div>
)

const AiCardView: React.FC<{ card?: AiCard | Record<string, never> }> = ({ card }) => {
  if (!card || !("decision_maker" in card)) return <Empty>Written when the incident reaches a pull request or escalation.</Empty>
  const c = card as AiCard
  return (
    <dl>
      <Row label="Decision maker">
        <span className="font-medium">{c.decision_maker.provider}</span>{" "}
        <span className="font-mono text-xs text-muted-foreground">{c.decision_maker.model}</span>{" "}
        <Badge variant="muted" className="ml-1 uppercase">{c.decision_maker.mode}</Badge>
        {c.decision_maker.fallback_used && <p className="mt-1 text-xs text-warning">Fallback: {c.decision_maker.fallback_reason}</p>}
      </Row>
      <Row label="Human oversight">
        <span className="capitalize">{c.human_oversight.approval_mode}</span> mode
        <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
          {c.human_oversight.decisions.map((d, i) => (
            <li key={i}>{d.gate}: <span className={d.approved ? "text-success" : "text-danger"}>{d.approved ? "approved" : "denied"}</span> by {d.by}</li>
          ))}
          <li>{c.human_oversight.merge}</li>
        </ul>
      </Row>
      <Row label="Data shared with AI">
        {c.data_shared.sent_to}
        <div className="mt-1.5 flex flex-wrap gap-1">
          {c.data_shared.evidence_sources.map((s) => <Badge key={s} variant="muted" className="font-mono">{s}</Badge>)}
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground">
          Redacted: {c.data_shared.secrets_redacted} secret(s), {c.data_shared.personal_data_redacted} personal value(s).
          Neutralized: {c.data_shared.injection_lines_neutralized} prompt-injection line(s). Never sent: {c.data_shared.never_sent}.
        </p>
      </Row>
      <Row label="Verification">
        Sandbox {c.verification.sandbox_isolated ? "isolated" : <span className="text-warning">not isolated</span>} ·
        regression test fails on old code: {String(c.verification.regression_test_fails_on_old_code)} · attempts: {c.verification.attempts ?? "—"}
      </Row>
      <Row label="Resources">
        <span className="tabular-nums">{c.usage.llm_calls} LLM calls · {c.usage.prompt_tokens + c.usage.completion_tokens} tokens · {c.usage.agent_steps} steps · {c.usage.elapsed_seconds}s</span>
      </Row>
      <Row label="Known limitations">
        <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">{c.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      </Row>
    </dl>
  )
}

export const DetailTabs: React.FC<{ incident?: Incident }> = ({ incident }) => {
  const id = incident?.id
  const active = isActive(incident?.status)
  const steps = useSteps(id, active).data || []
  const runs = useSandboxRuns(id, active).data || []
  const diff = useDiff(id, active).data
  const pm = usePostmortem(id, active).data?.markdown
  const [openRun, setOpenRun] = useState<number | null>(null)

  if (!incident) return null
  const d = incident.diagnosis

  return (
    <Card>
      <Tabs defaultValue="agent">
        <div className="flex flex-col gap-2 border-b p-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="scrollbar-thin -mx-2 overflow-x-auto px-2 sm:mx-0 sm:px-0">
            <TabsList className="w-max">
              <TabsTrigger value="agent">Agent steps <span className="ml-1.5 tabular-nums text-muted-foreground">{steps.length}</span></TabsTrigger>
              <TabsTrigger value="diff">Diff</TabsTrigger>
              <TabsTrigger value="sandbox">Sandbox <span className="ml-1.5 tabular-nums text-muted-foreground">{runs.length}</span></TabsTrigger>
              <TabsTrigger value="diagnosis">Diagnosis</TabsTrigger>
              <TabsTrigger value="postmortem">Post-mortem</TabsTrigger>
              <TabsTrigger value="ai">Responsible AI</TabsTrigger>
            </TabsList>
          </div>
          <Button asChild variant="ghost" size="sm" className="self-start text-muted-foreground sm:self-auto">
            <a href={api.auditUrl(incident.id)}><Download /> Audit JSON</a>
          </Button>
        </div>
        <CardContent className="scrollbar-thin max-h-[560px] overflow-y-auto p-4">
          <TabsContent value="agent" className="mt-0 space-y-2">
            {steps.length === 0 && <Empty>The coding agent's tool calls appear here.</Empty>}
            {steps.map((s) => (
              <div key={s.id} className={cn("rounded-lg border p-3", !s.ok && "border-danger/30 bg-danger/5")}>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                  <span className="font-mono tabular-nums text-muted-foreground">{clock(s.ts)}</span>
                  <Badge variant="muted">{TASK_LABEL[s.task]} · try {s.attempt}</Badge>
                  <span className="font-mono font-medium">{s.tool}</span>
                  <span className="min-w-0 truncate font-mono text-muted-foreground">{String(s.args.path ?? s.args.text ?? "")}</span>
                  {!s.ok && <Badge variant="destructive">refused</Badge>}
                </div>
                {s.thought && <p className="mt-1.5 text-sm text-foreground/80">{s.thought}</p>}
                <details className="group mt-1.5">
                  <summary className="flex cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                    <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" /> Result
                  </summary>
                  <pre className="scrollbar-thin mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-muted/40 p-2 font-mono text-[11px] text-muted-foreground">{s.result}</pre>
                </details>
              </div>
            ))}
          </TabsContent>

          <TabsContent value="diff" className="mt-0 space-y-4">
            <div className="space-y-1.5">
              <h4 className="text-xs font-medium text-muted-foreground">AutoSRE fix (vs. latest main)</h4>
              <DiffLines diff={diff?.diff} empty="No verified fix yet." />
            </div>
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground">
                <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" /> Suspect commit diff
              </summary>
              <div className="mt-1.5"><DiffLines diff={diff?.suspect_commit_diff} empty="No suspect commit yet." /></div>
            </details>
          </TabsContent>

          <TabsContent value="sandbox" className="mt-0 space-y-2">
            {runs.length === 0 && <Empty>No sandbox runs yet.</Empty>}
            {runs.map((r) => (
              <div key={r.id} className="rounded-lg border">
                <button type="button" onClick={() => setOpenRun(openRun === r.id ? null : r.id)}
                        className="flex w-full flex-wrap items-center gap-2 p-3 text-left text-xs hover:bg-accent/50">
                  <span className="font-mono tabular-nums text-muted-foreground">{clock(r.ts)}</span>
                  <Badge variant={r.passed ? "success" : "destructive"}>{r.passed ? "Passed" : r.timed_out ? "Timeout" : "Failed"}</Badge>
                  <span>{TASK_LABEL[r.task as keyof typeof TASK_LABEL] || r.task} · attempt {r.attempt}</span>
                  <Badge variant={r.isolated ? "outline" : r.engine === "cached" ? "info" : "warning"}>
                    {r.engine}{r.isolated || r.engine === "cached" ? "" : " · not isolated"}
                  </Badge>
                  {r.reproduced !== null && (
                    <span className={r.reproduced ? "text-success" : "text-danger"}>
                      {r.reproduced ? "Regression test fails on old code" : "Regression test does not fail on old code"}
                    </span>
                  )}
                  <span className="ml-auto tabular-nums text-muted-foreground">{r.duration_seconds}s</span>
                  <ChevronDown className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", openRun === r.id && "rotate-180")} />
                </button>
                {openRun === r.id && (
                  <pre className="scrollbar-thin max-h-80 overflow-auto whitespace-pre-wrap border-t bg-muted/40 p-3 font-mono text-[11px] text-muted-foreground">{r.output}</pre>
                )}
              </div>
            ))}
          </TabsContent>

          <TabsContent value="diagnosis" className="mt-0 space-y-3 text-sm">
            {!d?.findings ? <Empty>Diagnosis pending.</Empty> : (
              <>
                <p className="font-medium">{d.hypothesis}</p>
                <ul className="list-disc space-y-1 pl-5 text-muted-foreground">{d.findings.map((f) => <li key={f}>{f}</li>)}</ul>
                {d.delta && (
                  <p className="text-xs text-muted-foreground">
                    Change vs healthy baseline: {Object.entries(d.delta).map(([k, v]) => `${k} ${v >= 0 ? "+" : ""}${v}`).join(", ")}
                  </p>
                )}
                {(d.stuck_sessions?.groups || []).map((g) => (
                  <div key={g.query} className="rounded-lg border p-3">
                    <div className="text-sm">{g.count} × <span className="font-mono">{g.application_name}</span>, up to {Math.round(g.max_idle_seconds)}s stuck</div>
                    <pre className="mt-1.5 whitespace-pre-wrap break-all font-mono text-[11px] text-muted-foreground">{g.example_query}</pre>
                  </div>
                ))}
                {incident.mitigation?.terminated !== undefined && (
                  <p className="text-warning">Stop-the-bleeding ended {incident.mitigation.terminated} stuck session(s).</p>
                )}
              </>
            )}
          </TabsContent>

          <TabsContent value="postmortem" className="mt-0">
            {pm ? <Markdown source={pm} /> : <Empty>Written when the PR is opened (or on escalation).</Empty>}
          </TabsContent>

          <TabsContent value="ai" className="mt-0">
            <AiCardView card={incident.ai_card} />
          </TabsContent>
        </CardContent>
      </Tabs>
    </Card>
  )
}
