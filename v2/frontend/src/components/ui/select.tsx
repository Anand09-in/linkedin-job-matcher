import type { SelectHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

/** A plain, native `<select>` styled to match the rest of the design system
 * — deliberately not a Radix/Headless UI combobox: every use in this app is
 * a short, well-known list of options (status, sort field, feature name),
 * where the native element's accessibility/mobile behavior is already
 * better than a hand-rolled one would be for the added complexity. */
export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'flex h-9 w-full rounded-md border border-border bg-card px-3 py-1 text-sm shadow-sm outline-none transition-colors focus-visible:border-primary disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  )
}
