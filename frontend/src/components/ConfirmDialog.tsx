import React from "react"
import { AlertTriangle, Loader2 } from "lucide-react"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { cn } from "@/lib/utils"

interface ConfirmDialogProps {
  open: boolean
  title: string
  description: React.ReactNode
  confirmLabel: string
  tone?: "danger" | "warning"
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** shadcn AlertDialog: focus trap, Esc cancels, and Cancel is focused first so Enter is safe. */
export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  open, title, description, confirmLabel, tone = "danger", busy, onConfirm, onCancel,
}) => {
  const danger = tone === "danger"
  return (
    <AlertDialog open={open} onOpenChange={(next) => !next && !busy && onCancel()}>
      <AlertDialogContent>
        <AlertDialogHeader className="flex-row items-start gap-3 space-y-0">
          <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
                             danger ? "bg-danger/10 text-danger" : "bg-warning/10 text-warning")}>
            <AlertTriangle className="h-4 w-4" />
          </div>
          <div className="space-y-1.5">
            <AlertDialogTitle>{title}</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div>{description}</div>
            </AlertDialogDescription>
          </div>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={busy}
            onClick={(e) => {
              e.preventDefault() // keep the dialog open (with a spinner) until the request finishes
              onConfirm()
            }}
            className={danger ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                              : "bg-warning text-white hover:bg-warning/90 dark:text-zinc-950"}
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
