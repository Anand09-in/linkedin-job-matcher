import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../client'
import type { LLMSetting } from '../types'

export function useLLMSetting() {
  return useQuery({
    queryKey: ['settings', 'llm'],
    queryFn: async () => {
      const { data, error } = await api.GET('/settings/llm', {})
      if (error) throw error
      return data
    },
  })
}

export function useUpdateLLMSetting() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: LLMSetting) => {
      const { data, error } = await api.PUT('/settings/llm', { body })
      if (error) throw error
      return data
    },
    onSuccess: (data) => {
      qc.setQueryData(['settings', 'llm'], data)
    },
  })
}

export function useScraperCredential(site: string) {
  return useQuery({
    queryKey: ['settings', 'scraper-credentials', site],
    queryFn: async () => {
      const { data, error } = await api.GET('/settings/scraper-credentials/{site}', { params: { path: { site } } })
      if (error) throw error
      return data
    },
  })
}

export function useUpdateScraperCredential(site: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (value: string) => {
      const { data, error } = await api.PUT('/settings/scraper-credentials/{site}', { params: { path: { site } }, body: { value } })
      if (error) throw error
      return data
    },
    onSuccess: (data) => {
      qc.setQueryData(['settings', 'scraper-credentials', site], data)
    },
  })
}
