import { useMutation } from '@tanstack/react-query'
import { api } from '../client'
import type { FeatureKey } from '../types'

export interface RunFeatureParams {
  jobId: string
  feature: FeatureKey
  tone?: string
  word_count?: number
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

export interface RunAllFeaturesParams {
  jobId: string
  tone: string
  word_count: number
  regenerate?: boolean
}

/** Cover letter + interview prep + company research + resume improvement in
 * ONE LLM call (2026-09-08, explicit user request) — see
 * feature_service.run_all_features's docstring on the backend. Referral
 * message/search stay single-feature, via useRunFeature above. */
export function useRunAllFeatures() {
  return useMutation({
    mutationFn: async ({ jobId, regenerate = false, ...body }: RunAllFeaturesParams) => {
      const { data, error } = await api.POST('/features/all/{job_id}', {
        params: { path: { job_id: jobId } },
        body: { ...body, regenerate },
      })
      if (error) throw error
      return data
    },
  })
}
