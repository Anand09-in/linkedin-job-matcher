import { API_BASE_URL } from './client'

/** Export endpoints (GET /export/csv|excel) return a file stream, not JSON
 * — not a fit for openapi-fetch/React Query, so this just builds the URL
 * for a plain `<a href download>` link. */
export function exportUrl(format: 'csv' | 'excel', opts: { pipelineId?: string; hasScore?: boolean; minScore?: number } = {}) {
  const params = new URLSearchParams()
  if (opts.pipelineId) params.set('pipeline_id', opts.pipelineId)
  if (opts.hasScore !== undefined) params.set('has_score', String(opts.hasScore))
  if (opts.minScore !== undefined) params.set('min_score', String(opts.minScore))
  const qs = params.toString()
  return `${API_BASE_URL}/export/${format}${qs ? `?${qs}` : ''}`
}
