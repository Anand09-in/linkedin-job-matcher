import { Badge } from '@/components/ui/badge'
import { cn, formatScore, scoreTone } from '@/lib/utils'

const TONE_VARIANT = { good: 'success', ok: 'warning', low: 'destructive', neutral: 'secondary' } as const

export function ScoreBadge({ score }: { score: number | null | undefined }) {
  return <Badge variant={TONE_VARIANT[scoreTone(score)]}>{formatScore(score)}</Badge>
}

const STATUS_VARIANT: Record<string, 'default' | 'secondary' | 'success' | 'warning' | 'destructive' | 'outline'> = {
  new: 'secondary',
  saved: 'default',
  applied: 'warning',
  interview: 'default',
  offer: 'success',
  rejected: 'destructive',
  deleted: 'outline',
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={STATUS_VARIANT[status] ?? 'secondary'}>{status}</Badge>
}

/** Scrape run status — distinct from job StatusBadge above (different
 * domain: a run's own lifecycle, not application tracking). "running" and
 * "completed" are deliberately two different intensities of the same green
 * (in-progress vs. done, not two unrelated colors) so the run history list
 * reads as a single ramp: light green -> solid green, red on failure. */
const RUN_STATUS_CLASSES: Record<string, string> = {
  running: 'border-success/40 bg-success/20 text-success',
  completed: 'border-transparent bg-success text-success-foreground',
  failed: 'border-transparent bg-destructive text-destructive-foreground',
  cancelled: 'border-border bg-muted text-muted-foreground',
}

export function RunStatusBadge({ status }: { status: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium', RUN_STATUS_CLASSES[status] ?? 'border-border bg-muted text-muted-foreground')}>
      {status === 'running' && <span className="size-1.5 animate-pulse rounded-full bg-success" />}
      {status}
    </span>
  )
}
