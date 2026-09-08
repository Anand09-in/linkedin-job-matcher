import { Eye, FileText, Pencil, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { apiErrorMessage } from '@/api/client'
import { useCreateResume, useDeleteResume, useResume, useResumes, useUpdateResume } from '@/api/hooks/useResumes'
import type { Resume } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { EmptyBlock, ErrorBlock, LoadingBlock, Spinner } from '@/components/ui/spinner'
import { formatDateTime } from '@/lib/utils'
import { useToastStore } from '@/store/toastStore'

export function ResumesPage() {
  const { data: resumes, isLoading, isError, error } = useResumes()
  const [uploadOpen, setUploadOpen] = useState(false)
  const [editing, setEditing] = useState<Resume | null>(null)
  const [viewing, setViewing] = useState<Resume | null>(null)
  const deleteResume = useDeleteResume()
  const push = useToastStore((s) => s.push)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Resume Library</h1>
          <p className="text-sm text-muted-foreground">Upload multiple resumes and bind each to one or more pipelines.</p>
        </div>
        <Button onClick={() => setUploadOpen(true)}><Upload className="size-4" /> Upload resume</Button>
      </div>

      {isLoading && <LoadingBlock label="Loading resumes…" />}
      {isError && <ErrorBlock message={apiErrorMessage(error)} />}
      {resumes && resumes.length === 0 && <EmptyBlock message="No resumes uploaded yet." />}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {resumes?.map((resume) => (
          <Card key={resume.id}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><FileText className="size-4 shrink-0" /> {resume.name}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm text-muted-foreground">
              <p className="truncate">{resume.filename}</p>
              <p>Uploaded {formatDateTime(resume.uploaded_at)}</p>
              <p>{resume.parsed_profile ? 'Parsed profile cached' : 'Not parsed yet — will parse the next time it\'s used'}</p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setViewing(resume)}><Eye className="size-4" /> View</Button>
                <Button variant="outline" size="sm" onClick={() => setEditing(resume)}><Pencil className="size-4" /> Edit</Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={async () => {
                    try {
                      await deleteResume.mutateAsync(resume.id)
                      push('Resume deleted')
                    } catch (e) {
                      push(apiErrorMessage(e), 'error')
                    }
                  }}
                >
                  <Trash2 className="size-4 text-destructive" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />
      {editing && <EditDialog resume={editing} onClose={() => setEditing(null)} />}
      {viewing && <ViewDialog resumeId={viewing.id} name={viewing.name} onClose={() => setViewing(null)} />}
    </div>
  )
}

function ViewDialog({ resumeId, name, onClose }: { resumeId: string; name: string; onClose: () => void }) {
  const { data: resume, isLoading, isError, error } = useResume(resumeId)
  const profile = resume?.parsed_profile as
    | { summary?: string; current_title?: string; total_experience_years?: number; skills?: string[] }
    | null
    | undefined

  return (
    <Dialog open onClose={onClose} title={name} className="max-w-2xl">
      {isLoading && <LoadingBlock label="Loading resume…" />}
      {isError && <ErrorBlock message={apiErrorMessage(error)} />}
      {resume && (
        <div className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground">
            {resume.filename} · uploaded {formatDateTime(resume.uploaded_at)}
          </p>

          {profile ? (
            <div className="flex flex-col gap-2 rounded-md border border-border bg-muted/30 p-3 text-sm">
              <h4 className="text-xs font-semibold uppercase text-muted-foreground">Parsed profile (what the LLM sees on every batch call)</h4>
              <div className="flex flex-wrap gap-x-6 gap-y-1">
                <span><span className="text-muted-foreground">Title:</span> {profile.current_title ?? '—'}</span>
                <span><span className="text-muted-foreground">Experience:</span> {profile.total_experience_years != null ? `${profile.total_experience_years} yrs` : '—'}</span>
              </div>
              {profile.summary && <p className="text-muted-foreground">{profile.summary}</p>}
              {profile.skills && profile.skills.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {profile.skills.map((s) => (
                    <span key={s} className="rounded-full border border-border px-2 py-0.5 text-xs">{s}</span>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Not parsed yet — this normally happens automatically right after upload; it'll parse the next time a pipeline bound to this resume runs instead.</p>
          )}

          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">Full extracted text</h4>
            <pre className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3 text-xs text-muted-foreground">
              {resume.raw_text}
            </pre>
          </div>
        </div>
      )}
    </Dialog>
  )
}

function UploadDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const createResume = useCreateResume()
  const push = useToastStore((s) => s.push)

  function reset() {
    setName('')
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <Dialog open={open} onClose={() => { onClose(); reset() }} title="Upload resume">
      <form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault()
          const file = fileRef.current?.files?.[0]
          if (!file || !name) return
          try {
            await createResume.mutateAsync({ name, file })
            push('Resume uploaded')
            onClose()
            reset()
          } catch (err) {
            push(apiErrorMessage(err), 'error')
          }
        }}
      >
        <div className="flex flex-col gap-1">
          <Label htmlFor="resume-name">Name</Label>
          <Input id="resume-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. AI/ML Engineer Resume" required />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="resume-file">PDF file</Label>
          <input id="resume-file" ref={fileRef} type="file" accept="application/pdf" required className="text-sm" />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={createResume.isPending}>
            {createResume.isPending ? <Spinner /> : <Upload className="size-4" />} Upload
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function EditDialog({ resume, onClose }: { resume: Resume; onClose: () => void }) {
  const [name, setName] = useState(resume.name)
  const fileRef = useRef<HTMLInputElement>(null)
  const updateResume = useUpdateResume()
  const push = useToastStore((s) => s.push)

  return (
    <Dialog open onClose={onClose} title={`Edit "${resume.name}"`}>
      <form
        className="flex flex-col gap-4"
        onSubmit={async (e) => {
          e.preventDefault()
          const file = fileRef.current?.files?.[0]
          try {
            await updateResume.mutateAsync({ resumeId: resume.id, name: name !== resume.name ? name : undefined, file })
            push('Resume updated')
            onClose()
          } catch (err) {
            push(apiErrorMessage(err), 'error')
          }
        }}
      >
        <div className="flex flex-col gap-1">
          <Label htmlFor="edit-resume-name">Name</Label>
          <Input id="edit-resume-name" value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="edit-resume-file">Replace PDF (optional)</Label>
          <input id="edit-resume-file" ref={fileRef} type="file" accept="application/pdf" className="text-sm" />
          <p className="text-xs text-muted-foreground">Replacing the file re-parses it right away, same as a fresh upload.</p>
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={updateResume.isPending}>
            {updateResume.isPending ? <Spinner /> : null} Save
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
