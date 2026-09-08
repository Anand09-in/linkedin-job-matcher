import type { InputHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Checkbox({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="checkbox" className={cn('size-4 cursor-pointer rounded border-border accent-primary', className)} {...props} />
}
