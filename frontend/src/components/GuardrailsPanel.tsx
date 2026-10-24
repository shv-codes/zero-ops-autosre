import React from "react"
import { CheckCircle2, CircleDashed, ShieldAlert, ShieldCheck, XCircle } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { PanelHeader } from "@/components/Panel"
import { cn } from "@/lib/utils"
import type { GuardrailCheck } from "@/types/api"

const ICON = {
  passed: <CheckCircle2 className="h-4 w-4 text-success" />,
  failed: <XCircle className="h-4 w-4 text-danger" />,
  pending: <CircleDashed className="h-4 w-4 text-muted-foreground/60" />,
}

export const GuardrailsPanel: React.FC<{ checks: GuardrailCheck[] }> = ({ checks }) => {
  const passed = checks.filter((c) => c.status === "passed").length
  const failed = checks.filter((c) => c.status === "failed").length
  return (
    <Card className="h-full">
      <PanelHeader icon={failed ? ShieldAlert : ShieldCheck} title="Guardrails"
                   description="Enforced in code inside the agent's tools"
                   actions={<Badge variant={failed ? "warning" : "outline"} className="tabular-nums">{passed}/{checks.length} passed</Badge>} />
      <CardContent className="p-0">
        <ul className="divide-y">
          {checks.map((c) => (
            <li key={c.id} className="flex items-start gap-3 px-4 py-2.5">
              <span className="mt-0.5 shrink-0">{ICON[c.status]}</span>
              <div className="min-w-0">
                <div className={cn("text-sm", c.status === "pending" ? "text-muted-foreground" : "font-medium")}>{c.name}</div>
                <div className="text-xs leading-snug text-muted-foreground">{c.details}</div>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
