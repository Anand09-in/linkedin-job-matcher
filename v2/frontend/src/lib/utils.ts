import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Standard shadcn-style class merger: clsx for conditional classes, tailwind-merge to resolve conflicting Tailwind utility classes (e.g. `p-2` vs `p-4`) in favor of the later one. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function timeAgo(value: string | null | undefined): string {
  if (!value) return '—'
  const seconds = Math.floor((Date.now() - new Date(value).getTime()) / 1000)
  const units: [number, string][] = [
    [31536000, 'y'], [2592000, 'mo'], [86400, 'd'], [3600, 'h'], [60, 'm'],
  ]
  for (const [secs, label] of units) {
    const count = Math.floor(seconds / secs)
    if (count >= 1) return `${count}${label} ago`
  }
  return 'just now'
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return '—'
  return `${Math.round(score * 100)}%`
}

export function scoreTone(score: number | null | undefined): 'good' | 'ok' | 'low' | 'neutral' {
  if (score === null || score === undefined) return 'neutral'
  if (score >= 0.75) return 'good'
  if (score >= 0.55) return 'ok'
  return 'low'
}
