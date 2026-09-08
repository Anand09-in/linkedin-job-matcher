import { Briefcase, FileText, LayoutList, Settings as SettingsIcon, Workflow } from 'lucide-react'
import { NavLink, Outlet } from 'react-router'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/jobs', label: 'Job Results', icon: LayoutList },
  { to: '/pipelines', label: 'Pipelines', icon: Workflow },
  { to: '/resumes', label: 'Resumes', icon: FileText },
  { to: '/tracker', label: 'Tracker', icon: Briefcase },
  { to: '/settings', label: 'Settings', icon: SettingsIcon },
]

export function AppShell() {
  return (
    <div className="flex min-h-screen w-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-card px-3 py-4">
        <div className="mb-6 px-2">
          <h1 className="text-sm font-semibold">LinkedIn Job Matcher</h1>
          <p className="text-xs text-muted-foreground">v2</p>
        </div>
        <nav className="flex flex-col gap-1">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium transition-colors',
                  isActive ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="min-w-0 flex-1 overflow-x-hidden p-6">
        <Outlet />
      </main>
    </div>
  )
}
