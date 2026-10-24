import React, { useEffect, useRef, useState } from "react"
import { ArrowDownToLine, Check, Copy, Terminal } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { PanelHeader } from "@/components/Panel"
import { clock } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { LogTag, TimelineEntry } from "@/types/api"

const TAG: Record<LogTag, string> = {
  ALERT: "text-danger",
  MITIGATE: "text-warning",
  DIAG: "text-info",
  CORR: "text-violet",
  PATCH: "text-foreground",
  AGENT: "text-muted-foreground",
  GUARD: "text-violet",
  TEST: "text-success",
  PR: "text-success",
  LOOP: "text-info",
}

export const LiveTerminal: React.FC<{ timeline: TimelineEntry[] }> = ({ timeline }) => {
  const ref = useRef<HTMLDivElement>(null)
  const [follow, setFollow] = useState(true)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (follow && ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [timeline, follow])

  const copy = () => {
    navigator.clipboard.writeText(timeline.map((e) => `${clock(e.ts)} [${e.tag}] ${e.message}`).join("\n"))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <Card className="flex h-[360px] flex-col sm:h-[420px]">
      <PanelHeader
        icon={Terminal}
        title="Agent activity"
        description={`${timeline.length} events, streamed live`}
        actions={
          <>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" onClick={() => setFollow(!follow)} aria-pressed={follow}
                        aria-label="Follow new events" className={cn(follow && "bg-accent text-foreground")}>
                  <ArrowDownToLine />
                </Button>
              </TooltipTrigger>
              <TooltipContent>{follow ? "Following new events" : "Follow new events"}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" onClick={copy} aria-label="Copy log">
                  {copied ? <Check className="text-success" /> : <Copy />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{copied ? "Copied" : "Copy log"}</TooltipContent>
            </Tooltip>
          </>
        }
      />
      <CardContent ref={ref}
                   className="scrollbar-thin min-h-0 flex-1 space-y-1.5 overflow-y-auto bg-muted/30 p-3 font-mono text-[11.5px] leading-relaxed sm:p-4">
        {timeline.length === 0 && <div className="text-muted-foreground">Waiting for events…</div>}
        {timeline.map((e) => (
          <div key={e.id} className="grid grid-cols-[auto_1fr] gap-x-3 sm:grid-cols-[auto_4.5rem_1fr]">
            <span className="tabular-nums text-muted-foreground/70">{clock(e.ts)}</span>
            <span className={cn("font-medium sm:text-right", TAG[e.tag] || "text-muted-foreground")}>{e.tag}</span>
            <span className="col-span-2 whitespace-pre-wrap break-words text-foreground/85 sm:col-span-1">{e.message}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
