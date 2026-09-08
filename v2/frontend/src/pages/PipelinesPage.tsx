import { ChevronDown, ChevronRight, Play, Plus, Square, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { apiErrorMessage } from '@/api/client'
import {
  useClearScrapeRuns,
  useCreatePipeline,
  useDeletePipeline,
  usePipelines,
  useRejectedJobs,
  useUpdatePipeline,
} from '@/api/hooks/usePipelines'
import { useResumes } from '@/api/hooks/useResumes'
import { useCancelScrapeRun, useScrapeRuns, useTriggerScrape } from '@/api/hooks/useScrape'
import type { Pipeline, PipelineCreateRequest, RejectedJob } from '@/api/types'
import { RunStatusBadge } from '@/components/ScoreBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { EmptyBlock, ErrorBlock, LoadingBlock, Spinner } from '@/components/ui/spinner'
import { Textarea } from '@/components/ui/textarea'
import { timeAgo } from '@/lib/utils'
import { useToastStore } from '@/store/toastStore'

export function PipelinesPage() {
  const { data: pipelines, isLoading, isError, error } = usePipelines()
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<Pipeline | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Pipelines</h1>
          <p className="text-sm text-muted-foreground">Each pipeline is an independently runnable {'{resume, site, query, filters}'} bundle.</p>
        </div>
        <Button onClick={() => setCreateOpen(true)}><Plus className="size-4" /> New pipeline</Button>
      </div>

      {isLoading && <LoadingBlock label="Loading pipelines…" />}
      {isError && <ErrorBlock message={apiErrorMessage(error)} />}
      {pipelines && pipelines.length === 0 && <EmptyBlock message="No pipelines yet — create one to start scraping." />}

      <div className="flex flex-col gap-3">
        {pipelines?.map((pipeline) => (
          <PipelineCard
            key={pipeline.id}
            pipeline={pipeline}
            expanded={expanded === pipeline.id}
            onToggleExpand={() => setExpanded(expanded === pipeline.id ? null : pipeline.id)}
            onEdit={() => setEditing(pipeline)}
          />
        ))}
      </div>

      {createOpen && <PipelineFormDialog onClose={() => setCreateOpen(false)} />}
      {editing && <PipelineFormDialog pipeline={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function PipelineCard({
  pipeline,
  expanded,
  onToggleExpand,
  onEdit,
}: {
  pipeline: Pipeline
  expanded: boolean
  onToggleExpand: () => void
  onEdit: () => void
}) {
  const triggerScrape = useTriggerScrape()
  const cancelRun = useCancelScrapeRun()
  const deletePipeline = useDeletePipeline()
  const updatePipeline = useUpdatePipeline()
  const push = useToastStore((s) => s.push)
  const { data: resumes } = useResumes()
  const resumeName = resumes?.find((r) => r.id === pipeline.resume_id)?.name
  const [limit, setLimit] = useState('')

  // Polled every 4s (useScrapeRuns) — the same query PipelineDetails uses
  // when expanded, so mounting both here and there is one shared cache
  // entry, not a duplicate fetch. Runs are ordered newest-first, so [0] is
  // "the current or most recent run."
  const { data: runs } = useScrapeRuns(pipeline.id, 1)
  const latestRun = runs?.[0]
  const isRunning = latestRun?.status === 'running'

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-4">
        <div className="flex items-start justify-between gap-4">
          <button className="flex items-start gap-2 text-left" onClick={onToggleExpand}>
            {expanded ? <ChevronDown className="mt-0.5 size-4 shrink-0" /> : <ChevronRight className="mt-0.5 size-4 shrink-0" />}
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-semibold">{pipeline.name}</h3>
                {latestRun && <RunStatusBadge status={latestRun.status} />}
              </div>
              <p className="text-sm text-muted-foreground">
                {pipeline.site} · "{pipeline.query}" · {pipeline.locations.join(' / ') || 'any location'}
              </p>
              <p className="text-xs text-muted-foreground">
                Resume: {resumeName ?? (pipeline.resume_id ? 'unknown' : 'none (extract-only mode)')} · batch size {pipeline.batch_size}
              </p>
            </div>
          </button>
          <div className="flex shrink-0 items-center gap-2">
            {isRunning ? (
              <>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={async () => {
                    try {
                      await cancelRun.mutateAsync({ runId: latestRun.id, pipelineId: pipeline.id })
                      push('Stop requested — finishes after the batch in progress')
                    } catch (e) {
                      push(apiErrorMessage(e), 'error')
                    }
                  }}
                  disabled={cancelRun.isPending}
                >
                  {cancelRun.isPending ? <Spinner /> : <Square className="size-4" />} Stop
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={async () => {
                    if (!confirm(`Delete pipeline "${pipeline.name}"? This does not delete its saved jobs.`)) return
                    try {
                      await deletePipeline.mutateAsync(pipeline.id)
                      push('Pipeline deleted')
                    } catch (e) {
                      push(apiErrorMessage(e), 'error')
                    }
                  }}
                >
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              </>
            ) : (
              <>
                <label className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Checkbox
                    checked={pipeline.enabled}
                    onChange={(e) => updatePipeline.mutate({ pipelineId: pipeline.id, body: { enabled: e.target.checked } })}
                  />
                  Enabled
                </label>
                <Input
                  type="number"
                  min={1}
                  placeholder="limit"
                  value={limit}
                  onChange={(e) => setLimit(e.target.value)}
                  title="Optional: cap how many raw jobs this run scrapes before matching/filtering. Leave blank for no cap. Since jobs are only saved if they pass the match-score threshold, this isn't a guaranteed 'save exactly N' count — a lower limit with a resume-bound pipeline usually saves close to it, but a stricter filter can save fewer."
                  className="w-20"
                />
                <Button
                  size="sm"
                  onClick={async () => {
                    try {
                      await triggerScrape.mutateAsync({ pipelineId: pipeline.id, limit: limit ? Number(limit) : undefined })
                      push('Scrape run enqueued')
                    } catch (e) {
                      push(apiErrorMessage(e), 'error')
                    }
                  }}
                  disabled={triggerScrape.isPending}
                >
                  {triggerScrape.isPending ? <Spinner /> : <Play className="size-4" />} Run now
                </Button>
                <Button variant="outline" size="sm" onClick={onEdit}>Edit</Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={async () => {
                    if (!confirm(`Delete pipeline "${pipeline.name}"? This does not delete its saved jobs.`)) return
                    try {
                      await deletePipeline.mutateAsync(pipeline.id)
                      push('Pipeline deleted')
                    } catch (e) {
                      push(apiErrorMessage(e), 'error')
                    }
                  }}
                >
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              </>
            )}
          </div>
        </div>

        {expanded && <PipelineDetails pipelineId={pipeline.id} />}
      </CardContent>
    </Card>
  )
}

function rejectionLabel(r: RejectedJob): string {
  if (r.reason === 'below_match_score_threshold') {
    return r.match_score != null ? `below match threshold — scored ${r.match_score.toFixed(2)}` : 'below match threshold'
  }
  if (r.reason === 'exceeds_max_experience_years') {
    return r.experience_years_min != null ? `needs ${r.experience_years_min}+ yrs experience` : 'exceeds max experience'
  }
  if (r.reason === 'llm_batch_failed') return 'batch analysis failed'
  if (r.reason === 'missing_from_llm_response') return 'dropped from LLM response'
  return r.reason
}

function PipelineDetails({ pipelineId }: { pipelineId: string }) {
  const { data: runs } = useScrapeRuns(pipelineId, 5)
  const { data: rejected } = useRejectedJobs(pipelineId)
  const clearRuns = useClearScrapeRuns()
  const push = useToastStore((s) => s.push)
  const hasRunningRun = runs?.some((r) => r.status === 'running') ?? false

  return (
    <div className="grid grid-cols-1 gap-4 border-t border-border pt-3 md:grid-cols-2">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase text-muted-foreground">Run history (last 5)</h4>
          {runs && runs.length > 0 && (
            <button
              className="cursor-pointer text-muted-foreground hover:text-destructive disabled:cursor-not-allowed disabled:opacity-40"
              disabled={hasRunningRun || clearRuns.isPending}
              title={hasRunningRun ? "Can't clear while a run is active" : 'Clear run history'}
              onClick={async () => {
                if (!confirm('Clear this pipeline\'s run history? Saved jobs are not affected.')) return
                try {
                  await clearRuns.mutateAsync(pipelineId)
                  push('Run history cleared')
                } catch (e) {
                  push(apiErrorMessage(e), 'error')
                }
              }}
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
        {!runs || runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No runs yet.</p>
        ) : (
          <ul className="flex flex-col gap-1.5 text-sm">
            {runs.map((run) => (
              <li key={run.id} className="flex flex-col gap-0.5">
                <div className="flex items-center justify-between gap-2">
                  <RunStatusBadge status={run.status} />
                  <span className="text-muted-foreground">
                    seen {run.jobs_seen} · saved {run.jobs_saved} · rejected {run.jobs_rejected}
                  </span>
                  <span className="text-xs text-muted-foreground">{timeAgo(run.started_at)}</span>
                </div>
                {run.status === 'failed' && run.errors.length > 0 && (
                  <p className="truncate text-xs text-destructive" title={run.errors.join('; ')}>
                    {run.errors[0]}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h4 className="text-xs font-semibold uppercase text-muted-foreground">Recently rejected jobs</h4>
        <p className="mb-2 text-xs text-muted-foreground">Scraped but filtered out — below the match-score threshold or over the experience cap.</p>
        {!rejected || rejected.length === 0 ? (
          <p className="text-sm text-muted-foreground">None.</p>
        ) : (
          <ul className="flex flex-col gap-1.5 text-sm">
            {rejected.slice(0, 5).map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-2">
                <span className="truncate">{r.title} @ {r.company}</span>
                <span className="text-xs text-muted-foreground">{rejectionLabel(r)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

// Mirrors adapter.py's _RELEVANCE/_TIME/_TYPE/_EXPERIENCE/_REMOTE maps
// exactly (which in turn mirror linkedin-jobs-scraper's own filter enums) —
// these string values are sent to the API as-is and must match those keys
// or the adapter silently drops the unrecognized one.
const RELEVANCE_OPTIONS = ['RECENT', 'RELEVANT'] as const
const TIME_OPTIONS = ['DAY', 'WEEK', 'MONTH', 'ANY'] as const
const TYPE_OPTIONS = ['FULL_TIME', 'PART_TIME', 'CONTRACT', 'TEMPORARY', 'INTERNSHIP'] as const
const EXPERIENCE_OPTIONS = ['INTERNSHIP', 'ENTRY_LEVEL', 'ASSOCIATE', 'MID_SENIOR', 'DIRECTOR', 'EXECUTIVE'] as const
const REMOTE_OPTIONS = ['ON_SITE', 'REMOTE', 'HYBRID'] as const

function labelize(value: string): string {
  return value.split('_').map((w) => w[0] + w.slice(1).toLowerCase()).join(' ')
}

function CheckboxGroup({
  label, options, value, onChange,
}: {
  label: string
  options: readonly string[]
  value: string[]
  onChange: (next: string[]) => void
}) {
  return (
    <Field label={label}>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5">
        {options.map((opt) => (
          <label key={opt} className="flex items-center gap-1.5 text-sm">
            <Checkbox
              checked={value.includes(opt)}
              onChange={(e) => onChange(e.target.checked ? [...value, opt] : value.filter((v) => v !== opt))}
            />
            {labelize(opt)}
          </label>
        ))}
      </div>
    </Field>
  )
}

function PipelineFormDialog({ pipeline, onClose }: { pipeline?: Pipeline; onClose: () => void }) {
  const isEdit = !!pipeline
  const { data: resumes } = useResumes()
  const createPipeline = useCreatePipeline()
  const updatePipeline = useUpdatePipeline()
  const push = useToastStore((s) => s.push)

  const existingFilters = (pipeline?.filters ?? {}) as Record<string, unknown>

  const [name, setName] = useState(pipeline?.name ?? '')
  const [site, setSite] = useState(pipeline?.site ?? 'linkedin')
  const [query, setQuery] = useState(pipeline?.query ?? '')
  const [locations, setLocations] = useState(pipeline?.locations.join('\n') ?? '')
  const [resumeId, setResumeId] = useState(pipeline?.resume_id ?? '')
  const [batchSize, setBatchSize] = useState(pipeline?.batch_size ?? 5)
  const [minScore, setMinScore] = useState(pipeline?.min_match_score_override?.toString() ?? '')
  const [maxExperience, setMaxExperience] = useState(pipeline?.max_experience_years_override?.toString() ?? '')
  const [enabled, setEnabled] = useState(pipeline?.enabled ?? true)
  const [scheduleCron, setScheduleCron] = useState(pipeline?.schedule_cron ?? '')
  const [relevance, setRelevance] = useState((existingFilters.relevance as string) ?? 'RECENT')
  const [time, setTime] = useState((existingFilters.time as string) ?? 'MONTH')
  const [type, setType] = useState<string[]>((existingFilters.type as string[]) ?? [])
  const [experience, setExperience] = useState<string[]>((existingFilters.experience as string[]) ?? [])
  const [remote, setRemote] = useState<string[]>((existingFilters.on_site_or_remote as string[]) ?? [])

  const isPending = createPipeline.isPending || updatePipeline.isPending

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    const body: PipelineCreateRequest = {
      name,
      site,
      query,
      locations: locations.split('\n').map((l) => l.trim()).filter(Boolean),
      resume_id: resumeId || null,
      batch_size: batchSize,
      min_match_score_override: minScore ? Number(minScore) : null,
      max_experience_years_override: maxExperience ? Number(maxExperience) : null,
      enabled,
      schedule_cron: scheduleCron || null,
      filters: { relevance, time, type, experience, on_site_or_remote: remote },
    }
    try {
      if (isEdit) {
        await updatePipeline.mutateAsync({ pipelineId: pipeline.id, body })
        push('Pipeline updated')
      } else {
        await createPipeline.mutateAsync(body)
        push('Pipeline created')
      }
      onClose()
    } catch (err) {
      push(apiErrorMessage(err), 'error')
    }
  }

  return (
    <Dialog open onClose={onClose} title={isEdit ? `Edit "${pipeline.name}"` : 'New pipeline'} className="max-w-xl">
      <form className="flex flex-col gap-3" onSubmit={onSubmit}>
        <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} required /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Site">
            <Input value={site} onChange={(e) => setSite(e.target.value)} list="site-options" required />
            <datalist id="site-options"><option value="linkedin" /></datalist>
          </Field>
          <Field label="Batch size">
            <Input type="number" min={1} max={20} value={batchSize} onChange={(e) => setBatchSize(Number(e.target.value))} />
          </Field>
        </div>
        <Field label="Search query"><Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="AI Engineer" required /></Field>
        <Field label="Locations (one per line)">
          <Textarea
            value={locations}
            onChange={(e) => setLocations(e.target.value)}
            placeholder={'Bangalore, India\nRemote'}
            rows={3}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Relevance">
            <Select value={relevance} onChange={(e) => setRelevance(e.target.value)}>
              {RELEVANCE_OPTIONS.map((o) => <option key={o} value={o}>{labelize(o)}</option>)}
            </Select>
          </Field>
          <Field label="Posted within">
            <Select value={time} onChange={(e) => setTime(e.target.value)}>
              {TIME_OPTIONS.map((o) => <option key={o} value={o}>{labelize(o)}</option>)}
            </Select>
          </Field>
        </div>
        <CheckboxGroup label="Employment type" options={TYPE_OPTIONS} value={type} onChange={setType} />
        <CheckboxGroup label="Experience level" options={EXPERIENCE_OPTIONS} value={experience} onChange={setExperience} />
        <CheckboxGroup label="On-site / remote" options={REMOTE_OPTIONS} value={remote} onChange={setRemote} />
        <Field label="Resume (leave empty for extract-only mode)">
          <Select value={resumeId} onChange={(e) => setResumeId(e.target.value)}>
            <option value="">No resume — extract only</option>
            {resumes?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Min match score override">
            <Input type="number" min={0} max={1} step={0.05} value={minScore} onChange={(e) => setMinScore(e.target.value)} placeholder="default" />
          </Field>
          <Field label="Max experience override">
            <Input type="number" min={0} value={maxExperience} onChange={(e) => setMaxExperience(e.target.value)} placeholder="default" />
          </Field>
        </div>
        <Field label="Schedule (cron — stored only, not yet executed automatically)">
          <Input value={scheduleCron} onChange={(e) => setScheduleCron(e.target.value)} placeholder="0 */6 * * *" />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={isPending}>{isPending ? <Spinner /> : null} {isEdit ? 'Save' : 'Create'}</Button>
        </div>
      </form>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}
