import { CheckCircle2, HelpCircle, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { apiErrorMessage } from '@/api/client'
import {
  useCheckScraperCredential,
  useLLMSetting,
  useScraperCredential,
  useUpdateLLMSetting,
  useUpdateScraperCredential,
} from '@/api/hooks/useSettings'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorBlock, LoadingBlock, Spinner } from '@/components/ui/spinner'
import { timeAgo } from '@/lib/utils'
import { useToastStore } from '@/store/toastStore'

const COMMON_MODELS = [
  'mistral.mistral-large-3-675b-instruct',
  'anthropic.claude-3-haiku-20240307-v1:0',
  'anthropic.claude-3-5-sonnet-20241022-v2:0',
]

export function SettingsPage() {
  const { data: setting, isLoading, isError, error } = useLLMSetting()
  const updateSetting = useUpdateLLMSetting()
  const push = useToastStore((s) => s.push)

  const [model, setModel] = useState('')
  const [temperature, setTemperature] = useState(0.1)
  const [maxTokens, setMaxTokens] = useState(2000)

  useEffect(() => {
    if (setting) {
      setModel(setting.model)
      setTemperature(setting.temperature)
      setMaxTokens(setting.max_tokens)
    }
  }, [setting])

  if (isLoading) return <LoadingBlock label="Loading settings…" />
  if (isError) return <ErrorBlock message={apiErrorMessage(error)} />

  return (
    <div className="flex max-w-lg flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">
          One active Bedrock model, used for every extraction, match, and on-demand feature call — no per-feature override.
        </p>
      </div>

      <Card>
        <CardHeader><CardTitle>Active LLM</CardTitle></CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-3"
            onSubmit={async (e) => {
              e.preventDefault()
              try {
                await updateSetting.mutateAsync({ provider: 'bedrock', model, temperature, max_tokens: maxTokens })
                push('Settings updated — takes effect on the next call, no restart needed')
              } catch (err) {
                push(apiErrorMessage(err), 'error')
              }
            }}
          >
            <div className="flex flex-col gap-1">
              <Label htmlFor="model">Bedrock model ID</Label>
              <Input id="model" value={model} onChange={(e) => setModel(e.target.value)} list="model-options" required />
              <datalist id="model-options">
                {COMMON_MODELS.map((m) => <option key={m} value={m} />)}
              </datalist>
              <p className="text-xs text-muted-foreground">Must be a model your AWS account has Bedrock Marketplace access to.</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor="temperature">Temperature</Label>
                <Input id="temperature" type="number" min={0} max={1} step={0.05} value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="max-tokens">Max tokens</Label>
                <Input id="max-tokens" type="number" min={256} step={256} value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} />
              </div>
            </div>
            <Button type="submit" disabled={updateSetting.isPending} className="w-fit">
              {updateSetting.isPending ? <Spinner /> : null} Save
            </Button>
          </form>
        </CardContent>
      </Card>

      <LinkedInSessionCard />
    </div>
  )
}

function LinkedInSessionCard() {
  const { data: credential, isLoading } = useScraperCredential('linkedin')
  const updateCredential = useUpdateScraperCredential('linkedin')
  const checkCredential = useCheckScraperCredential('linkedin')
  const push = useToastStore((s) => s.push)
  const [cookie, setCookie] = useState('')

  return (
    <Card>
      <CardHeader>
        <CardTitle>LinkedIn Session</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          The <code>li_at</code> session cookie LinkedIn pipelines scrape with. Expires roughly every 30 days — when it
          does, LinkedIn silently serves the logged-out public search page instead of erroring, so a run just quietly
          finds nothing. Update it here any time, no restart needed.
        </p>

        {!isLoading && credential && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Status:</span>
            {!credential.configured ? (
              <span className="text-muted-foreground">Not configured</span>
            ) : (
              <CheckStatus status={credential.last_check_status} checkedAt={credential.last_checked_at} />
            )}
          </div>
        )}

        <form
          className="flex flex-col gap-2"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!cookie) return
            try {
              await updateCredential.mutateAsync(cookie)
              setCookie('')
              push('LinkedIn cookie saved — takes effect on the next scrape run')
            } catch (err) {
              push(apiErrorMessage(err), 'error')
            }
          }}
        >
          <Label htmlFor="li-at-cookie">Paste new li_at cookie value</Label>
          <div className="flex gap-2">
            <Input
              id="li-at-cookie"
              type="password"
              value={cookie}
              onChange={(e) => setCookie(e.target.value)}
              placeholder="AQEDAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              autoComplete="off"
            />
            <Button type="submit" disabled={!cookie || updateCredential.isPending}>
              {updateCredential.isPending ? <Spinner /> : null} Save
            </Button>
          </div>
        </form>

        <Button
          variant="outline"
          size="sm"
          className="w-fit"
          disabled={!credential?.configured || checkCredential.isPending}
          onClick={async () => {
            try {
              await checkCredential.mutateAsync()
              push('Checking cookie against LinkedIn — status updates below in a few seconds')
            } catch (err) {
              push(apiErrorMessage(err), 'error')
            }
          }}
        >
          {checkCredential.isPending ? <Spinner /> : null} Test cookie
        </Button>
      </CardContent>
    </Card>
  )
}

function CheckStatus({ status, checkedAt }: { status?: string | null; checkedAt?: string | null }) {
  if (!status) return <span className="flex items-center gap-1 text-muted-foreground"><HelpCircle className="size-4" /> Not tested yet</span>
  if (status === 'valid') {
    return <span className="flex items-center gap-1 text-success"><CheckCircle2 className="size-4" /> Valid (checked {timeAgo(checkedAt)})</span>
  }
  if (status === 'invalid') {
    return <span className="flex items-center gap-1 text-destructive"><XCircle className="size-4" /> Invalid or expired (checked {timeAgo(checkedAt)})</span>
  }
  return <span className="flex items-center gap-1 text-warning"><HelpCircle className="size-4" /> Check failed — try again (checked {timeAgo(checkedAt)})</span>
}
