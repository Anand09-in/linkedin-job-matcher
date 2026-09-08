import { Download, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { exportUrl } from '@/api/export'
import { useBulkDeleteJobsBefore, useDeleteJob, useJobs, useJobsCountBefore } from '@/api/hooks/useJobs'
import { usePipelines } from '@/api/hooks/usePipelines'
import { JOB_STATUSES } from '@/api/types'
import { ScoreBadge, StatusBadge } from '@/components/ScoreBadge'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { EmptyBlock, ErrorBlock, LoadingBlock } from '@/components/ui/spinner'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { apiErrorMessage } from '@/api/client'
import { formatDate } from '@/lib/utils'
import { useToastStore } from '@/store/toastStore'
import { useUIStore } from '@/store/uiStore'

const PAGE_SIZE = 25

export function JobResultsPage() {
  const { selectedPipelineId, setSelectedPipelineId } = useUIStore()
  const [status, setStatus] = useState('')
  const [company, setCompany] = useState('')
  const [title, setTitle] = useState('')
  const [minScore, setMinScore] = useState('')
  const [sortBy, setSortBy] = useState('match_score')
  const [offset, setOffset] = useState(0)
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)

  const { data: pipelines } = usePipelines()
  const { data: jobs, isLoading, isError, error } = useJobs({
    pipeline_id: selectedPipelineId ?? undefined,
    status: status || undefined,
    company: company || undefined,
    title: title || undefined,
    min_score: minScore ? Number(minScore) : undefined,
    sort_by: sortBy,
    limit: PAGE_SIZE,
    offset,
  })
  const deleteJob = useDeleteJob()
  const push = useToastStore((s) => s.push)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Job Results</h1>
          <p className="text-sm text-muted-foreground">Scored jobs saved by your pipelines.</p>
        </div>
        <div className="flex gap-2">
          <a href={exportUrl('csv', { pipelineId: selectedPipelineId ?? undefined })}>
            <Button variant="outline" size="sm">
              <Download className="size-4" /> CSV
            </Button>
          </a>
          <a href={exportUrl('excel', { pipelineId: selectedPipelineId ?? undefined })}>
            <Button variant="outline" size="sm">
              <Download className="size-4" /> Excel
            </Button>
          </a>
          <Button variant="destructive" size="sm" onClick={() => setBulkDeleteOpen(true)}>
            <Trash2 className="size-4" /> Bulk delete
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <Field label="Pipeline">
          <Select value={selectedPipelineId ?? ''} onChange={(e) => { setSelectedPipelineId(e.target.value || null); setOffset(0) }} className="w-44">
            <option value="">All pipelines</option>
            {pipelines?.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </Select>
        </Field>
        <Field label="Status">
          <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }} className="w-36">
            <option value="">Any (not deleted)</option>
            {JOB_STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </Select>
        </Field>
        {status === 'rejected' && (
          <p className="max-w-xs text-xs text-muted-foreground">
            This is jobs YOU marked "rejected" after reviewing them — jobs a pipeline auto-filtered out during
            scraping never become Job rows at all; see "Recently rejected jobs" on the Pipelines page for those.
          </p>
        )}
        <Field label="Company">
          <Input value={company} onChange={(e) => { setCompany(e.target.value); setOffset(0) }} placeholder="Acme" className="w-36" />
        </Field>
        <Field label="Title">
          <Input value={title} onChange={(e) => { setTitle(e.target.value); setOffset(0) }} placeholder="Engineer" className="w-40" />
        </Field>
        <Field label="Min score">
          <Input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={minScore}
            onChange={(e) => { setMinScore(e.target.value); setOffset(0) }}
            className="w-24"
          />
        </Field>
        <Field label="Sort by">
          <Select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="w-36">
            <option value="match_score">Match score</option>
            <option value="scraped_at">Scraped date</option>
            <option value="experience">Experience</option>
            <option value="company">Company</option>
            <option value="title">Title</option>
          </Select>
        </Field>
      </div>

      {isLoading && <LoadingBlock label="Loading jobs…" />}
      {isError && <ErrorBlock message={apiErrorMessage(error)} />}
      {jobs && jobs.length === 0 && <EmptyBlock message="No jobs match these filters." />}

      {jobs && jobs.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Company</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Experience</TableHead>
              <TableHead>Seniority</TableHead>
              <TableHead>Remote</TableHead>
              <TableHead>Posted</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job) => (
              <TableRow key={job.id}>
                <TableCell className="max-w-64 truncate font-medium">
                  <Link to={`/jobs/${job.id}`} className="hover:text-primary hover:underline">{job.title}</Link>
                </TableCell>
                <TableCell className="max-w-40 truncate">{job.company}</TableCell>
                <TableCell className="max-w-40 truncate text-muted-foreground">{job.location ?? '—'}</TableCell>
                <TableCell><ScoreBadge score={job.match_score} /></TableCell>
                <TableCell><StatusBadge status={job.status} /></TableCell>
                <TableCell className="text-muted-foreground">{job.experience_years_min != null ? `${job.experience_years_min}+ yrs` : '—'}</TableCell>
                <TableCell className="text-muted-foreground">{job.seniority_level ?? '—'}</TableCell>
                <TableCell className="text-muted-foreground">{job.remote_policy ?? '—'}</TableCell>
                <TableCell className="text-muted-foreground">{formatDate(job.date_posted ?? job.scraped_at)}</TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={async () => {
                      try {
                        await deleteJob.mutateAsync(job.id)
                        push('Job deleted')
                      } catch (e) {
                        push(apiErrorMessage(e), 'error')
                      }
                    }}
                  >
                    <Trash2 className="size-4 text-destructive" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {jobs && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Showing {jobs.length === 0 ? 0 : offset + 1}–{offset + jobs.length}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              Previous
            </Button>
            <Button variant="outline" size="sm" disabled={jobs.length < PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)}>
              Next
            </Button>
          </div>
        </div>
      )}

      <BulkDeleteDialog open={bulkDeleteOpen} onClose={() => setBulkDeleteOpen(false)} />
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
      {label}
      {children}
    </label>
  )
}

function BulkDeleteDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [beforeDate, setBeforeDate] = useState('')
  const { data: count } = useJobsCountBefore(beforeDate || undefined)
  const bulkDelete = useBulkDeleteJobsBefore()
  const push = useToastStore((s) => s.push)

  return (
    <Dialog open={open} onClose={onClose} title="Bulk delete jobs by date">
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">
          Permanently deletes every job posted on or before the chosen date (hard delete — cannot be undone). Falls back to
          scraped date when a job has no posted date.
        </p>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-muted-foreground" htmlFor="before-date">Before date</label>
          <Input id="before-date" type="date" value={beforeDate} onChange={(e) => setBeforeDate(e.target.value)} />
        </div>
        {beforeDate && (
          <p className="text-sm">
            This will delete <span className="font-semibold">{count?.count ?? '…'}</span> job(s).
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button
            variant="destructive"
            disabled={!beforeDate || bulkDelete.isPending}
            onClick={async () => {
              try {
                const result = await bulkDelete.mutateAsync(beforeDate)
                push(`Deleted ${result.deleted_count} job(s)`)
                onClose()
              } catch (e) {
                push(apiErrorMessage(e), 'error')
              }
            }}
          >
            <Trash2 className="size-4" /> Delete permanently
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
