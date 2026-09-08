import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'

export interface JobFilters {
  pipeline_id?: string
  status?: string
  min_score?: number
  max_score?: number
  company?: string
  title?: string
  location?: string
  seniority?: string
  remote_policy?: string
  has_score?: boolean
  sort_by?: string
  limit?: number
  offset?: number
}

export function useJobs(filters: JobFilters) {
  return useQuery({
    queryKey: ['jobs', filters],
    queryFn: async () => {
      const { data, error } = await api.GET('/jobs', { params: { query: filters } })
      if (error) throw error
      return data
    },
    placeholderData: (prev) => prev,
  })
}

export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ['jobs', jobId],
    queryFn: async () => {
      const { data, error } = await api.GET('/jobs/{job_id}', { params: { path: { job_id: jobId! } } })
      if (error) throw error
      return data
    },
    enabled: !!jobId,
  })
}

export function useJobStats() {
  return useQuery({
    queryKey: ['jobs', 'stats'],
    queryFn: async () => {
      const { data, error } = await api.GET('/jobs/stats', {})
      if (error) throw error
      return data
    },
  })
}

export function useJobsCountBefore(beforeDate: string | undefined) {
  return useQuery({
    queryKey: ['jobs', 'count-before', beforeDate],
    queryFn: async () => {
      const { data, error } = await api.GET('/jobs/count-before', { params: { query: { before_date: beforeDate! } } })
      if (error) throw error
      return data
    },
    enabled: !!beforeDate,
  })
}

export function useUpdateJobStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ jobId, status }: { jobId: string; status: string }) => {
      const { data, error } = await api.PATCH('/jobs/{job_id}/status', {
        params: { path: { job_id: jobId } },
        body: { status },
      })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

export function useDeleteJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (jobId: string) => {
      const { error } = await api.DELETE('/jobs/{job_id}', { params: { path: { job_id: jobId } } })
      if (error) throw error
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}

export function useBulkDeleteJobsBefore() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (beforeDate: string) => {
      const { data, error } = await api.DELETE('/jobs', { params: { query: { before_date: beforeDate } } })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}
