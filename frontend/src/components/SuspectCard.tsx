import React from "react"
import { GitCommit } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { PanelHeader } from "@/components/Panel"
import type { Incident } from "@/types/api"

const RISK_VARIANT = { Low: "success", Medium: "warning", High: "destructive" } as const

export const SuspectCard: React.FC<{ incident?: Incident }> = ({ incident }) => {
  const s = incident?.suspect
  const commit = s?.commit
  const loc = s?.location
  const risk = incident?.fix?.risk
  const confidence = Math.round((s?.confidence || 0) * 100)

  return (
    <Card>
      <PanelHeader icon={GitCommit} title="Root cause" description={commit ? `Commit ${commit.short_sha}` : "Correlating commits"}
                   actions={risk && <Badge variant={RISK_VARIANT[risk]}>Risk: {risk}</Badge>} />
      <CardContent className="space-y-3 p-4">
        {!commit ? (
          <p className="text-sm text-muted-foreground">The suspect commit appears here after correlation.</p>
        ) : (
          <>
            <div>
              <p className="text-sm font-medium leading-snug">{commit.message}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">by {commit.author}</p>
            </div>
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Confidence</span><span className="tabular-nums font-medium text-foreground">{confidence}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-violet" style={{ width: `${confidence}%` }} />
              </div>
            </div>
            {loc?.start_line && (
              <div className="truncate font-mono text-xs text-muted-foreground">
                {loc.file}:{loc.start_line}-{loc.end_line}{loc.function && ` · ${loc.function}()`}
              </div>
            )}
            {loc?.snippet && (
              <pre className="scrollbar-thin max-h-36 overflow-auto rounded-md border bg-muted/40 p-2.5 font-mono text-[11px] leading-relaxed text-foreground/85">{loc.snippet}</pre>
            )}
            {(s?.evidence || []).length > 0 && (
              <ul className="space-y-1">
                {(s?.evidence || []).slice(0, 4).map((e) => (
                  <li key={e} className="flex gap-2 text-xs leading-snug text-muted-foreground">
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/60" />{e}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
