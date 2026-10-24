import React from "react"
import { CardHeader } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface PanelHeaderProps {
  icon?: React.ElementType
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
  className?: string
}

/** Consistent card header used by every dashboard panel. */
export const PanelHeader: React.FC<PanelHeaderProps> = ({ icon: Icon, title, description, actions, className }) => (
  <CardHeader className={cn("flex flex-row items-center justify-between gap-3 space-y-0 border-b px-4 py-3", className)}>
    <div className="flex min-w-0 items-center gap-2.5">
      {Icon && <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />}
      <div className="min-w-0">
        <h3 className="truncate text-sm font-medium leading-none">{title}</h3>
        {description && <p className="mt-1 truncate text-xs text-muted-foreground">{description}</p>}
      </div>
    </div>
    {actions && <div className="flex shrink-0 items-center gap-1.5">{actions}</div>}
  </CardHeader>
)
