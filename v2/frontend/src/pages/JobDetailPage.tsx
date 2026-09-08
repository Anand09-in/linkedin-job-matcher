import { ArrowLeft, ExternalLink, RefreshCw, Trash2, Zap } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { apiErrorMessage } from '@/api/client'
import { useRunAllFeatures, useRunFeature } from '@/api/hooks/useFeatures'
import { useDeleteJob, useJob, useUpdateJobStatus } from '@/api/hooks/useJobs'
import { useLLMSetting } from '@/api/hooks/useSettings'
import { BUNDLED_FEATURES, FEATURES, JOB_STATUSES, type FeatureKey, type FeatureRunResponse } from '@/api/types'
import { ScoreBadge, StatusBadge } from '@/components/ScoreBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { ErrorBlock, LoadingBlock, Spinner } from '@/components/ui/spinner'
import { Tabs } from '@/components/ui/tabs'
import { formatDate } from '@/lib/utils'
import { useToastStore } from '@/store/toastStore'

export function JobDetailPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const { data: job, isLoading, isError, error } = useJob(jobId)
  const updateStatus = useUpdateJobStatus()
  const deleteJob = useDeleteJob()
  const push = useToastStore((s) => s.push)

  if (isLoading) return <LoadingBlock label="Loading job…" />
  if (isError || !job) return <ErrorBlock message={apiErrorMessage(error) ?? 'Job not found.'} />

  return (
    <div className="flex flex-col gap-4">
      <Link to="/jobs" className="flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> Back to Job Results
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{job.title}</h1>
          <p className="text-sm text-muted-foreground">
            {job.company} {job.location ? `· ${job.location}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ScoreBadge score={job.match_score} />
          <Select
            value={job.status}
            onChange={async (e) => {
              try {
                await updateStatus.mutateAsync({ jobId: job.id, status: e.target.value })
                push('Status updated')
              } catch (err) {
                push(apiErrorMessage(err), 'error')
              }
            }}
            className="w-32"
          >
            {[...JOB_STATUSES, 'deleted'].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </Select>
          <a href={job.apply_link ?? job.link} target="_blank" rel="noreferrer">
            <Button variant="outline" size="sm"><ExternalLink className="size-4" /> Open posting</Button>
          </a>
          <Button
            variant="destructive"
            size="sm"
            onClick={async () => {
              await deleteJob.mutateAsync(job.id)
              push('Job deleted')
              navigate('/jobs')
            }}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Match assessment</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-3 text-sm">
            <p className="text-muted-foreground">{job.match_rationale ?? 'This job has not been scored against a resume.'}</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Matched skills</h4>
                <SkillList skills={job.matched_skills} empty="None recorded" tone="success" />
              </div>
              <div>
                <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Missing skills</h4>
                <SkillList skills={job.missing_skills} empty="None flagged" tone="destructive" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Details</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <DetailRow label="Seniority" value={job.seniority_level} />
            <DetailRow label="Employment type" value={job.employment_type} />
            <DetailRow label="Remote policy" value={job.remote_policy} />
            <DetailRow label="Min experience" value={job.experience_years_min != null ? `${job.experience_years_min}+ yrs` : null} />
            <DetailRow label="Education" value={job.education_required} />
            <DetailRow label="Posted" value={formatDate(job.date_posted)} />
            <DetailRow label="Status" value={<StatusBadge status={job.status} />} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Salary benchmark</CardTitle></CardHeader>
        <CardContent className="text-sm">
          <SalaryBenchmark benchmark={job.salary_benchmark} status={job.salary_enrichment_status} />
        </CardContent>
      </Card>

      {job.description && (
        <Card>
          <CardHeader><CardTitle>Job description</CardTitle></CardHeader>
          <CardContent className="max-h-96 overflow-y-auto whitespace-pre-wrap text-sm text-muted-foreground">
            {job.description}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>On-demand features</CardTitle></CardHeader>
        <CardContent>
          <FeaturePanel jobId={job.id} />
        </CardContent>
      </Card>
    </div>
  )
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value ?? '—'}</span>
    </div>
  )
}

function SkillList({ skills, empty, tone }: { skills: string[] | null | undefined; empty: string; tone: 'success' | 'destructive' }) {
  if (!skills || skills.length === 0) return <p className="text-xs text-muted-foreground">{empty}</p>
  return (
    <div className="flex flex-wrap gap-1">
      {skills.map((s) => (
        <span key={s} className={`rounded-full border px-2 py-0.5 text-xs ${tone === 'success' ? 'border-success/30 text-success' : 'border-destructive/30 text-destructive'}`}>
          {s}
        </span>
      ))}
    </div>
  )
}

function SalaryBenchmark({ benchmark, status }: { benchmark: Record<string, unknown> | null | undefined; status: string }) {
  if (status === 'pending') return <p className="text-muted-foreground">Salary lookup is still running…</p>
  if (status === 'failed' || !benchmark) return <p className="text-muted-foreground">Salary lookup did not find a usable estimate.</p>
  const min = benchmark.min_amount as number | null
  const max = benchmark.max_amount as number | null
  const currency = benchmark.currency as string
  const confidence = benchmark.confidence as string
  return (
    <div className="flex flex-col gap-1">
      <p className="text-lg font-semibold">
        {min != null || max != null ? `${min ?? '?'} – ${max ?? '?'} ${currency}` : 'No figure found'}
        <span className="ml-2 text-xs font-normal text-muted-foreground">({confidence} confidence)</span>
      </p>
      <p className="text-xs text-muted-foreground">{benchmark.source_note as string}</p>
    </div>
  )
}

function FeaturePanel({ jobId }: { jobId: string }) {
  const [active, setActive] = useState<FeatureKey>('cover_letter')
  const [results, setResults] = useState<Partial<Record<FeatureKey, FeatureRunResponse>>>({})
  const [tone, setTone] = useState('professional')
  const [wordCount, setWordCount] = useState(250)
  const [contactName, setContactName] = useState('')
  const [contactTitle, setContactTitle] = useState('')
  const [channel, setChannel] = useState<'linkedin_connection_note' | 'linkedin_dm'>('linkedin_connection_note')
  const runFeature = useRunFeature()
  const runAllFeatures = useRunAllFeatures()
  const { data: llmSetting } = useLLMSetting()
  const push = useToastStore((s) => s.push)

  const activeMeta = FEATURES.find((f) => f.key === active)!
  const result = results[active]
  const allBundledGenerated = BUNDLED_FEATURES.every((f) => results[f])

  async function run(regenerate = false) {
    try {
      const data = await runFeature.mutateAsync({
        jobId,
        feature: active,
        tone: active === 'cover_letter' ? tone : undefined,
        word_count: active === 'cover_letter' ? wordCount : undefined,
        contact_name: active === 'referral_message' ? contactName || undefined : undefined,
        contact_title: active === 'referral_message' ? contactTitle || undefined : undefined,
        channel: active === 'referral_message' ? channel : undefined,
        regenerate,
      })
      setResults((r) => ({ ...r, [active]: data }))
    } catch (e) {
      push(apiErrorMessage(e), 'error')
    }
  }

  async function runAll(regenerate = false) {
    try {
      const data = await runAllFeatures.mutateAsync({ jobId, tone, word_count: wordCount, regenerate })
      setResults((r) => ({
        ...r,
        ...Object.fromEntries(
          BUNDLED_FEATURES.map((f) => [
            f,
            { feature: f, job_id: data.job_id, params: {}, cached: data.cached, result: data.results[f] },
          ]),
        ),
      }))
      push(data.cached ? 'Loaded from cache — no LLM call needed' : 'Generated cover letter, interview prep, company research, and resume improvement in one call')
    } catch (e) {
      push(apiErrorMessage(e), 'error')
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <Tabs value={active} onChange={setActive} items={FEATURES.map((f) => ({ value: f.key, label: f.label }))} />
        {llmSetting && (
          <span className="whitespace-nowrap text-xs text-muted-foreground" title="Every feature above uses this one model, configured in Settings — never a per-feature override.">
            Generated with <span className="font-mono">{llmSetting.model}</span>
          </span>
        )}
      </div>

      <div className="flex flex-col gap-2 rounded-md border border-border bg-muted/20 p-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="flex items-end gap-2">
            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
              Cover letter tone
              <Select value={tone} onChange={(e) => setTone(e.target.value)} className="w-36">
                <option value="professional">Professional</option>
                <option value="confident">Confident</option>
                <option value="friendly">Friendly</option>
              </Select>
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
              Target word count
              <Input
                type="number"
                min={100}
                max={600}
                step={25}
                value={wordCount}
                onChange={(e) => setWordCount(Number(e.target.value))}
                className="w-28"
              />
            </label>
          </div>
          <div className="flex gap-2">
            <Button size="sm" onClick={() => runAll(false)} disabled={runAllFeatures.isPending}>
              {runAllFeatures.isPending ? <Spinner /> : <Zap className="size-4" />} Generate All
            </Button>
            {allBundledGenerated && (
              <Button size="sm" variant="outline" onClick={() => runAll(true)} disabled={runAllFeatures.isPending}>
                <RefreshCw className="size-4" /> Regenerate All
              </Button>
            )}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Fills in Cover Letter, Interview Prep, Company Research, and Resume Improvement together — one LLM call, not four.
        </p>
      </div>

      {active === 'referral_message' && (
        <div className="flex flex-col gap-2">
          <div className="flex gap-4 text-sm">
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                checked={channel === 'linkedin_connection_note'}
                onChange={() => setChannel('linkedin_connection_note')}
              />
              Not connected yet — connection request (300 char limit)
            </label>
            <label className="flex items-center gap-1.5">
              <input type="radio" checked={channel === 'linkedin_dm'} onChange={() => setChannel('linkedin_dm')} />
              Already connected — DM / InMail
            </label>
          </div>
          <div className="flex gap-2">
            <Input placeholder="Contact name (optional)" value={contactName} onChange={(e) => setContactName(e.target.value)} />
            <Input placeholder="Contact title (optional)" value={contactTitle} onChange={(e) => setContactTitle(e.target.value)} />
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <Button onClick={() => run(false)} disabled={runFeature.isPending}>
          {runFeature.isPending ? <Spinner /> : null} Generate
        </Button>
        {result && (
          <Button variant="outline" onClick={() => run(true)} disabled={runFeature.isPending}>
            <RefreshCw className="size-4" /> Regenerate
          </Button>
        )}
        {!activeMeta.needsResume && (
          <span className="self-center text-xs text-muted-foreground">Doesn't require a resume-bound pipeline.</span>
        )}
      </div>

      {result && (
        <div className="rounded-md border border-border bg-muted/30 p-4">
          <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
            {result.cached ? 'Served from cache' : 'Freshly generated'}
          </div>
          <FeatureResult feature={active} result={result.result} />
        </div>
      )}
    </div>
  )
}

function FeatureResult({ feature, result }: { feature: FeatureKey; result: Record<string, unknown> }) {
  switch (feature) {
    case 'cover_letter':
      return <p className="whitespace-pre-wrap text-sm">{result.cover_letter as string}</p>
    case 'referral_message':
      return <p className="whitespace-pre-wrap text-sm">{result.message as string}</p>
    case 'company_research':
      return (
        <div className="flex flex-col gap-2 text-sm">
          <p>{result.overall_impression as string}</p>
          <ListSection title="Green flags" items={result.green_flags as string[]} />
          <ListSection title="Red flags" items={result.red_flags as string[]} />
          <ListSection title="Culture signals" items={result.culture_signals as string[]} />
          <ListSection title="Tech stack" items={result.tech_stack_hints as string[]} />
        </div>
      )
    case 'resume_improvement':
      return (
        <div className="flex flex-col gap-2 text-sm">
          <p className="font-semibold">Overall fit: {result.overall_fit_grade as string}</p>
          <p>{result.summary_rewrite as string}</p>
          <ListSection title="Top actions" items={result.top_actions as string[]} />
          <ListSection title="Keywords to add" items={result.keywords_to_add as string[]} />
        </div>
      )
    case 'interview_prep': {
      const questions = (result.questions as { category: string; question: string; answer_framework: string; key_points: string[] }[]) ?? []
      return (
        <div className="flex flex-col gap-3 text-sm">
          {questions.map((q, i) => (
            <div key={i} className="border-b border-border pb-2 last:border-0">
              <p className="text-xs font-semibold uppercase text-muted-foreground">{q.category} · {q.answer_framework}</p>
              <p className="font-medium">{q.question}</p>
              <ul className="ml-4 list-disc text-muted-foreground">
                {q.key_points?.map((k, j) => <li key={j}>{k}</li>)}
              </ul>
            </div>
          ))}
          <ListSection title="Prep tips" items={result.prep_tips as string[]} />
        </div>
      )
    }
    case 'referral_search': {
      const contacts = (result.contacts as { name: string; title: string | null; profile_url: string | null; note: string | null }[]) ?? []
      return (
        <div className="flex flex-col gap-2 text-sm">
          <p className="text-xs text-muted-foreground">{result.caveat as string}</p>
          {contacts.length === 0 && <p className="text-muted-foreground">No contacts found.</p>}
          {contacts.map((c, i) => (
            <div key={i} className="border-b border-border pb-2 last:border-0">
              <p className="font-medium">
                {c.profile_url ? <a href={c.profile_url} target="_blank" rel="noreferrer" className="hover:underline">{c.name}</a> : c.name}
              </p>
              <p className="text-muted-foreground">{c.title}</p>
              <p className="text-xs text-muted-foreground">{c.note}</p>
            </div>
          ))}
        </div>
      )
    }
    default:
      return <pre className="overflow-x-auto text-xs">{JSON.stringify(result, null, 2)}</pre>
  }
}

function ListSection({ title, items }: { title: string; items: string[] | undefined }) {
  if (!items || items.length === 0) return null
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase text-muted-foreground">{title}</h4>
      <ul className="ml-4 list-disc">
        {items.map((item, i) => <li key={i}>{item}</li>)}
      </ul>
    </div>
  )
}
