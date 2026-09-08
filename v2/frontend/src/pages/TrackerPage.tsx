import { useMemo } from 'react'
import { Link } from 'react-router'
import { apiErrorMessage } from '@/api/client'
import { useJobs, useJobStats } from '@/api/hooks/useJobs'
import { usePipelines } from '@/api/hooks/usePipelines'
import { JOB_STATUSES } from '@/api/types'
import { ScoreBadge } from '@/components/ScoreBadge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { ErrorBlock, LoadingBlock } from '@/components/ui/spinner'
import { useUIStore } from '@/store/uiStore'

export function TrackerPage() {
  const { selectedPipelineId, setSelectedPipelineId } = useUIStore()
  const { data: pipelines } = usePipelines()
  const { data: stats } = useJobStats()
  const { data: jobs, isLoading, isError, error } = useJobs({
    pipeline_id: selectedPipelineId ?? undefined,
    limit: 200, // GET /jobs caps `limit` at 200 (le=200) — the tracker board is a full-funnel view, not paginated, so this is just "as many as the API allows in one call"
    sort_by: 'scraped_at',
  })

  const byStatus = useMemo(() => {
    const groups: Record<string, typeof jobs> = {}
    for (const status of JOB_STATUSES) groups[status] = []
    for (const job of jobs ?? []) {
      if (!groups[job.status]) groups[job.status] = []
      groups[job.status]!.push(job)
    }
    return groups
  }, [jobs])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Tracker</h1>
          <p className="text-sm text-muted-foreground">Application funnel across your saved jobs.</p>
        </div>
        <Select value={selectedPipelineId ?? ''} onChange={(e) => setSelectedPipelineId(e.target.value || null)} className="w-48">
          <option value="">All pipelines</option>
          {pipelines?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
      </div>

      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Total jobs" value={stats.total_jobs} />
          <StatCard label="With description" value={stats.with_description} />
          <StatCard label="Scored" value={stats.with_match_score} />
          <StatCard label="Avg match score" value={`${Math.round(stats.avg_match_score * 100)}%`} />
        </div>
      )}

      {isLoading && <LoadingBlock label="Loading tracker…" />}
      {isError && <ErrorBlock message={apiErrorMessage(error)} />}

      {jobs && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {JOB_STATUSES.map((status) => (
            <div key={status} className="flex flex-col gap-2">
              <div className="flex items-center justify-between px-1">
                <h3 className="text-sm font-semibold capitalize">{status}</h3>
                <span className="text-xs text-muted-foreground">{byStatus[status]?.length ?? 0}</span>
              </div>
              <div className="flex flex-col gap-2">
                {byStatus[status]?.map((job) => (
                  <Link key={job.id} to={`/jobs/${job.id}`}>
                    <Card className="p-2 transition-colors hover:border-primary">
                      <CardContent className="flex flex-col gap-1 p-1 text-xs">
                        <span className="truncate font-medium">{job.title}</span>
                        <span className="truncate text-muted-foreground">{job.company}</span>
                        <ScoreBadge score={job.match_score} />
                      </CardContent>
                    </Card>
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <CardHeader className="pb-0">
        <CardTitle className="text-2xl">{value}</CardTitle>
      </CardHeader>
      <CardContent className="pt-1 text-xs text-muted-foreground">{label}</CardContent>
    </Card>
  )
}
