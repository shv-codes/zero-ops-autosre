import React from "react"
import { toast } from "sonner"
import { ExternalLink, GitBranch, GitMerge, GitPullRequest, Users } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PanelHeader } from "@/components/Panel"
import { useMerge, useTeammatePush } from "@/hooks/useAutoSRE"
import type { Incident } from "@/types/api"

export const PrCard: React.FC<{ incident?: Incident }> = ({ incident }) => {
  const merge = useMerge()
  const teammate = useTeammatePush()
  const pr = incident?.pull_request
  const isLocal = pr?.provider === "local"
  const open = pr?.state === "open"

  const state = !pr?.number ? null
    : pr.state === "merged" || incident?.status === "RESOLVED" ? { label: "Merged", variant: "violet" as const }
    : incident?.status === "READY_TO_MERGE" ? { label: "Ready to merge", variant: "success" as const }
    : incident?.status === "UPDATING_PR" ? { label: "Repairing", variant: "warning" as const }
    : pr.draft ? { label: "Draft", variant: "muted" as const }
    : { label: pr.state === "closed" ? "Closed" : "Open", variant: "outline" as const }

  return (
    <Card>
      <PanelHeader icon={GitPullRequest} title="Pull request"
                   description={pr?.number ? `#${pr.number} · ${pr.rounds || 0} repair round(s)` : "Opened after the sandbox passes"}
                   actions={state && <Badge variant={state.variant}>{state.label}</Badge>} />
      <CardContent className="space-y-3 p-4">
        {!pr?.number ? (
          <p className="text-sm text-muted-foreground">
            {incident?.status === "ESCALATED" ? "No PR: escalated to a human. See the post-mortem tab." : "Opened after the fix passes the sandbox."}
          </p>
        ) : (
          <>
            <p className="text-sm font-medium leading-snug">{pr.title}</p>
            <div className="flex min-w-0 items-center gap-1.5 font-mono text-xs text-muted-foreground">
              <GitBranch className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{pr.head_branch}</span>
              <span className="shrink-0">→</span>
              <span className="shrink-0">{pr.base_branch}</span>
            </div>
            {pr.url?.startsWith("http") ? (
              <Button asChild variant="outline" size="sm" className="w-full sm:w-auto">
                <a href={pr.url} target="_blank" rel="noreferrer">Open on GitHub <ExternalLink /></a>
              </Button>
            ) : (
              <p className="truncate text-xs text-muted-foreground">{pr.url} (local origin)</p>
            )}
            <p className="text-xs text-muted-foreground">AutoSRE never merges. A human does.</p>
            {isLocal && open && (
              <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:flex-wrap">
                <Button size="sm" variant="outline" disabled={teammate.isPending}
                        onClick={() => teammate.mutate(undefined, {
                          onSuccess: (r) => toast.info("Teammate pushed to main", { description: r.message }),
                          onError: (e) => toast.error((e as Error).message),
                        })}>
                  <Users /> Simulate teammate push
                </Button>
                {incident?.status === "READY_TO_MERGE" && (
                  <Button size="sm" disabled={merge.isPending}
                          onClick={() => merge.mutate(incident.id, {
                            onSuccess: (r) => toast.success(`Merged ${r.branch} into ${r.base}`, {
                              description: r.github_url ? `Pushed to ${r.github_url}` : "Updated the local main branch.",
                            }),
                            onError: (e) => toast.error((e as Error).message),
                          })}>
                    <GitMerge /> Merge as reviewer
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
