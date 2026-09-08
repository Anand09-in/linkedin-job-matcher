import { cn } from '@/lib/utils'

export function Tabs<T extends string>({
  value,
  onChange,
  items,
}: {
  value: T
  onChange: (value: T) => void
  items: { value: T; label: string }[]
}) {
  return (
    <div className="flex flex-wrap gap-1 border-b border-border">
      {items.map((item) => (
        <button
          key={item.value}
          onClick={() => onChange(item.value)}
          className={cn(
            'cursor-pointer rounded-t-md border-b-2 px-3 py-2 text-sm font-medium transition-colors',
            value === item.value
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground',
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
