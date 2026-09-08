import { useMutation } from '@tanstack/react-query'
import { api } from '../client'
import type { FeatureKey } from '../types'

export interface RunFeatureParams {
  jobId: string
  feature: FeatureKey
  tone?: string
  channel?: string
  contact_name?: string
  contact_title?: string
  regenerate?: boolean
}

/** A mutation, not a query, even though the backend itself caches by (job,
 * resume, feature, params) — this is still an explicit, potentially
 * LLM-cost-incurring user action (a button click), not passive data
 * fetching; JobDetailPage keeps the last result per feature tab in local
 * state from onSuccess rather than a query cache entry. */
export function useRunFeature() {
  return useMutation({
    mutationFn: async ({ jobId, feature, regenerate = false, ...body }: RunFeatureParams) => {
      const { data, error } = await api.POST('/features/{feature}/{job_id}', {
        params: { path: { feature, job_id: jobId } },
        body: { ...body, regenerate },
      })
      if (error) throw error
      return data
    },
  })
}
