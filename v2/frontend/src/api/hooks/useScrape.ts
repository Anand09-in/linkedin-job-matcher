import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'

export function useScrapeRuns(pipelineId: string | undefined, limit = 20) {
  return useQuery({
    // `limit` is part of the key — PipelineCard asks for just the latest
    // run (limit=1) to know if it's running, PipelineDetails' history list
    // asks for 5; without limit in the key they'd collide in the cache and
    // whichever mounted first would win for both. invalidateQueries with
    // just ['scrape','runs',pipelineId] (below, and in useTriggerScrape/
    // useCancelScrapeRun) still matches every limit variant — TanStack
    // Query's default invalidation is a prefix match.
    queryKey: ['scrape', 'runs', pipelineId, limit],
    queryFn: async () => {
      const { data, error } = await api.GET('/scrape/runs', { params: { query: { pipeline_id: pipelineId, limit } } })
      if (error) throw error
      return data
    },
    enabled: !!pipelineId,
    // Runs are worker-driven and finish in the background — poll while this
    // page is open so status/counters update without a manual refresh.
    refetchInterval: 4000,
  })
}

export function useTriggerScrape() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ pipelineId, limit }: { pipelineId: string; limit?: number }) => {
      const { data, error } = await api.POST('/scrape', { body: { pipeline_id: pipelineId, limit: limit ?? null } })
      if (error) throw error
      return data
    },
    onSuccess: (_data, { pipelineId }) => {
      qc.invalidateQueries({ queryKey: ['scrape', 'runs', pipelineId] })
    },
  })
}

export function useCancelScrapeRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ runId }: { runId: string; pipelineId: string }) => {
      const { data, error } = await api.POST('/scrape/{run_id}/cancel', { params: { path: { run_id: runId } } })
      if (error) throw error
      return data
    },
    onSuccess: (_data, { pipelineId }) => {
      qc.invalidateQueries({ queryKey: ['scrape', 'runs', pipelineId] })
    },
  })
}
