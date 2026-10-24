import React, { useState } from "react"
import { ChevronDown, GitCommitHorizontal } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PanelHeader } from "@/components/Panel"
import { isActive, useDiff } from "@/hooks/useAutoSRE"
import { cn } from "@/lib/utils"
import type { Incident } from "@/types/api"

export const DiffLines: React.FC<{ diff?: string; empty?: string; className?: string }> = ({ diff, empty, className }) => {
  if (!diff) return <p className="text-sm text-muted-foreground">{empty || "The repaired diff appears here after the fix is pushed."}</p>
  return (
    <pre className={cn("scrollbar-thin overflow-auto rounded-md border bg-muted/30 py-2 font-mono text-[11px] leading-relaxed", className)}>
      {diff.split("\n").map((line, i) => (
        <div key={i} className={cn("px-3",
          line.startsWith("+++") || line.startsWith("---") ? "text-muted-foreground"
            : line.startsWith("+") ? "bg-success/10 text-success"
            : line.startsWith("-") ? "bg-danger/10 text-danger"
            : line.startsWith("@@") ? "text-info" : "text-foreground/75")}>{line || " "}</div>
      ))}
    </pre>
  )
}

const Section: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <section className="space-y-1.5">
    <h4 className="text-xs font-medium text-muted-foreground">{label}</h4>
    {children}
  </section>
)

export const ReviewPanel: React.FC<{ incident?: Incident }> = ({ incident }) => {
  const active = isActive(incident?.status)
  const diff = useDiff(incident?.id, active).data?.diff
  const reviews = incident?.pull_request?.reviews || []
  const latest = reviews[reviews.length - 1]
  const [logOpen, setLogOpen] = useState(false)

  if (!incident?.pull_request?.number && reviews.length === 0) return null
  const base = incident?.pull_request?.base_branch || "main"

  return (
    <Card>
      <PanelHeader icon={GitCommitHorizontal} title="Commit review" description={`Keeping the PR mergeable as ${base} moves`}
                   actions={latest && <Badge variant={latest.conflicts ? "warning" : "success"}>{latest.conflicts ? "Merge conflict" : "Clean"}</Badge>} />
      <CardContent className="p-4">
        {!latest ? (
          <p className="text-sm text-muted-foreground">
            Waiting for a new commit on {base}. The conflict check, the checks and the fix show up here.
          </p>
        ) : (
          <div className="grid gap-5 lg:grid-cols-2">
            <div className="space-y-4">
              <Section label="New commit">
                <p className="text-sm font-medium">{latest.message}</p>
                <p className="text-xs text-muted-foreground">by {latest.author} on {base}</p>
              </Section>
              <Section label="Merge conflicts">
                {latest.conflicts ? (
                  <ul className="space-y-0.5 font-mono text-xs text-warning">
                    {(latest.conflict_files.length ? latest.conflict_files : ["conflict detected"]).map((file) => <li key={file}>{file}</li>)}
                  </ul>
                ) : <p className="text-sm text-success">Clean merge. No files conflict.</p>}
              </Section>
              <Section label="Checks">
                {!latest.sandbox ? (
                  <p className="text-sm text-muted-foreground">Running the branch checks…</p>
                ) : (
                  <div className="space-y-2 rounded-md border p-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <Badge variant={latest.sandbox.passed ? "success" : "destructive"}>{latest.sandbox.passed ? "Passed" : "Failed"}</Badge>
                      <span className="text-muted-foreground">{latest.sandbox.engine} · {latest.sandbox.duration_seconds}s</span>
                    </div>
                    <ul className="space-y-0.5 font-mono text-[11px] text-foreground/80">
                      {latest.sandbox.commands.filter((c) => !c.includes("test_user_activity")).map((c) => <li key={c} className="break-all">$ {c}</li>)}
                    </ul>
                    <Button variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground" onClick={() => setLogOpen((o) => !o)}>
                      <ChevronDown className={cn("transition-transform", logOpen && "rotate-180")} />
                      {logOpen ? "Hide log" : "Show log"}
                    </Button>
                    {logOpen && (
                      <pre className="scrollbar-thin max-h-48 overflow-auto whitespace-pre-wrap rounded bg-muted/50 p-2 font-mono text-[11px] text-muted-foreground">{latest.sandbox.output}</pre>
                    )}
                  </div>
                )}
              </Section>
            </div>
            <Section label="Fix">
              <p className="text-sm text-foreground/85">{latest.repair_summary || "The repair summary appears when the branch is pushed."}</p>
              <DiffLines diff={diff} className="max-h-72" />
            </Section>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
