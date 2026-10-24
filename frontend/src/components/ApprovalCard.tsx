import React, { useState } from "react"
import { toast } from "sonner"
import { Check, ShieldQuestion, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { useDecide } from "@/hooks/useAutoSRE"
import type { Incident } from "@/types/api"

/** Review mode: AutoSRE is waiting for a person before an impactful step. */
export const ApprovalCard: React.FC<{ incident?: Incident }> = ({ incident }) => {
  const decide = useDecide()
  const [name, setName] = useState("")
  const pending = incident?.pending_approval
  if (!incident || !pending?.gate || pending.decision) return null

  const send = (decision: "approve" | "deny") =>
    decide.mutate(
      { id: incident.id, gate: pending.gate!, decision, by: name || undefined },
      {
        onSuccess: () => toast.success(decision === "approve" ? "Approved" : "Denied", { description: pending.title }),
        onError: (e) => toast.error((e as Error).message),
      },
    )

  return (
    <Card role="alert" className="border-info/40 bg-info/[0.04] p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
        <div className="flex min-w-0 flex-1 gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-info/10 text-info">
            <ShieldQuestion className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold">Approval needed</span>
              <Badge variant="info" className="capitalize">{pending.gate}</Badge>
            </div>
            <p className="mt-1 text-sm">{pending.title}</p>
            <p className="mt-1 break-words font-mono text-xs text-muted-foreground">
              {Object.entries(pending.details || {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ")}
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name (optional)"
                 aria-label="Your name" className="sm:w-44" />
          <div className="grid grid-cols-2 gap-2">
            <Button disabled={decide.isPending} onClick={() => send("approve")}><Check /> Approve</Button>
            <Button variant="outline" disabled={decide.isPending} onClick={() => send("deny")}><X /> Deny</Button>
          </div>
        </div>
      </div>
    </Card>
  )
}
