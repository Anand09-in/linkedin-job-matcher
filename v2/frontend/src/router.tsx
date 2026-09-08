import { Navigate, createBrowserRouter } from 'react-router'
import { AppShell } from '@/components/layout/AppShell'
import { JobDetailPage } from '@/pages/JobDetailPage'
import { JobResultsPage } from '@/pages/JobResultsPage'
import { PipelinesPage } from '@/pages/PipelinesPage'
import { ResumesPage } from '@/pages/ResumesPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { TrackerPage } from '@/pages/TrackerPage'

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: '/', element: <Navigate to="/jobs" replace /> },
      { path: '/jobs', element: <JobResultsPage /> },
      { path: '/jobs/:jobId', element: <JobDetailPage /> },
      { path: '/pipelines', element: <PipelinesPage /> },
      { path: '/resumes', element: <ResumesPage /> },
      { path: '/tracker', element: <TrackerPage /> },
      { path: '/settings', element: <SettingsPage /> },
    ],
  },
])
