import { CheckCircle2, X, XCircle } from 'lucide-react'
import { useToastStore } from '@/store/toastStore'
import { cn } from '@/lib/utils'

export function Toaster() {
  const { toasts, dismiss } = useToastStore()
  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={cn(
            'flex items-center gap-2 rounded-md border px-3 py-2 text-sm shadow-lg',
            t.variant === 'success' ? 'border-success/30 bg-card text-success' : 'border-destructive/30 bg-card text-destructive',
          )}
        >
          {t.variant === 'success' ? <CheckCircle2 className="size-4 shrink-0" /> : <XCircle className="size-4 shrink-0" />}
          <span className="text-foreground">{t.message}</span>
          <button onClick={() => dismiss(t.id)} className="cursor-pointer text-muted-foreground hover:text-foreground">
            <X className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  )
}
