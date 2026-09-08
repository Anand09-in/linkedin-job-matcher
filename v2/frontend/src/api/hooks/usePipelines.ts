import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import type { PipelineCreateRequest, PipelineUpdateRequest } from '../types'

export function usePipelines(enabledOnly = false) {
  return useQuery({
    queryKey: ['pipelines', { enabledOnly }],
    queryFn: async () => {
      const { data, error } = await api.GET('/pipelines', { params: { query: { enabled_only: enabledOnly } } })
      if (error) throw error
      return data
    },
  })
}

export function usePipeline(pipelineId: string | undefined) {
  return useQuery({
    queryKey: ['pipelines', pipelineId],
    queryFn: async () => {
      const { data, error } = await api.GET('/pipelines/{pipeline_id}', { params: { path: { pipeline_id: pipelineId! } } })
      if (error) throw error
      return data
    },
    enabled: !!pipelineId,
  })
}

export function useRejectedJobs(pipelineId: string | undefined) {
  return useQuery({
    queryKey: ['pipelines', pipelineId, 'rejected-jobs'],
    queryFn: async () => {
      const { data, error } = await api.GET('/pipelines/{pipeline_id}/rejected-jobs', {
        params: { path: { pipeline_id: pipelineId! } },
      })
      if (error) throw error
      return data
    },
    enabled: !!pipelineId,
  })
}

export function useCreatePipeline() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: PipelineCreateRequest) => {
      const { data, error } = await api.POST('/pipelines', { body })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipelines'] })
    },
  })
}

export function useUpdatePipeline() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ pipelineId, body }: { pipelineId: string; body: PipelineUpdateRequest }) => {
      const { data, error } = await api.PUT('/pipelines/{pipeline_id}', { params: { path: { pipeline_id: pipelineId } }, body })
      if (error) throw error
      return data
    },
    onSuccess: (_data, { pipelineId }) => {
      qc.invalidateQueries({ queryKey: ['pipelines'] })
      qc.invalidateQueries({ queryKey: ['pipelines', pipelineId] })
    },
  })
}

export function useClearScrapeRuns() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (pipelineId: string) => {
      const { data, error } = await api.DELETE('/pipelines/{pipeline_id}/scrape-runs', {
        params: { path: { pipeline_id: pipelineId } },
      })
      if (error) throw error
      return data
    },
    onSuccess: (_data, pipelineId) => {
      qc.invalidateQueries({ queryKey: ['scrape', 'runs', pipelineId] })
      // Deleting scrape runs cascades to their RejectedJob rows server-side
      // (ondelete="CASCADE") — this list is stale too, not just the runs
      // themselves, even though this mutation never touched it directly.
      qc.invalidateQueries({ queryKey: ['pipelines', pipelineId, 'rejected-jobs'] })
    },
  })
}

export function useDeletePipeline() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (pipelineId: string) => {
      const { error } = await api.DELETE('/pipelines/{pipeline_id}', { params: { path: { pipeline_id: pipelineId } } })
      if (error) throw error
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipelines'] })
    },
  })
}
