import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, uploadForm } from '../client'
import type { ResumeDetail } from '../types'

export function useResumes() {
  return useQuery({
    queryKey: ['resumes'],
    queryFn: async () => {
      const { data, error } = await api.GET('/resumes', {})
      if (error) throw error
      return data
    },
  })
}

export function useResume(resumeId: string | undefined) {
  return useQuery({
    queryKey: ['resumes', resumeId],
    queryFn: async () => {
      const { data, error } = await api.GET('/resumes/{resume_id}', { params: { path: { resume_id: resumeId! } } })
      if (error) throw error
      return data
    },
    enabled: !!resumeId,
  })
}

export function useCreateResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ name, file }: { name: string; file: File }) => {
      const form = new FormData()
      form.append('name', name)
      form.append('file', file)
      return (await uploadForm('/resumes', 'POST', form)) as ResumeDetail
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['resumes'] })
    },
  })
}

export function useUpdateResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ resumeId, name, file }: { resumeId: string; name?: string; file?: File }) => {
      const form = new FormData()
      if (name !== undefined) form.append('name', name)
      if (file !== undefined) form.append('file', file)
      return (await uploadForm(`/resumes/${resumeId}`, 'PUT', form)) as ResumeDetail
    },
    onSuccess: (_data, { resumeId }) => {
      qc.invalidateQueries({ queryKey: ['resumes'] })
      qc.invalidateQueries({ queryKey: ['resumes', resumeId] })
    },
  })
}

export function useDeleteResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (resumeId: string) => {
      const { error } = await api.DELETE('/resumes/{resume_id}', { params: { path: { resume_id: resumeId } } })
      if (error) throw error
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['resumes'] })
    },
  })
}
