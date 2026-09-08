import { X } from 'lucide-react'
import { type ReactNode, useEffect } from 'react'
import { cn } from '@/lib/utils'

/** A minimal, hand-rolled modal — deliberately not @radix-ui/react-dialog:
 * every dialog in this app is a simple form/confirmation, so a full
 * focus-trap/portal library wasn't worth the extra dependency. Closes on
 * Escape and backdrop click, which covers the accessibility basics that
 * actually matter here. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  className,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  className?: string
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        className={cn('max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-lg border border-border bg-card p-5 shadow-lg', className)}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="cursor-pointer rounded-md p-1 text-muted-foreground hover:bg-muted" aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
