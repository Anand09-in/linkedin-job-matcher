import type { components } from './schema'

export type Job = components['schemas']['JobResponse']
export type JobStats = components['schemas']['JobStatsResponse']
export type Resume = components['schemas']['ResumeResponse']
export type ResumeDetail = components['schemas']['ResumeDetailResponse']
export type Pipeline = components['schemas']['PipelineResponse']
export type PipelineCreateRequest = components['schemas']['PipelineCreateRequest']
export type PipelineUpdateRequest = components['schemas']['PipelineUpdateRequest']
export type RejectedJob = components['schemas']['RejectedJobResponse']
export type ScrapeRun = components['schemas']['ScrapeRunResponse']
export type LLMSetting = components['schemas']['LLMSettingResponse']
export type FeatureRunResponse = components['schemas']['FeatureRunResponse']

export const JOB_STATUSES = ['new', 'saved', 'applied', 'interview', 'offer', 'rejected'] as const
export type JobStatus = (typeof JOB_STATUSES)[number]

export const FEATURES = [
  { key: 'cover_letter', label: 'Cover Letter', needsResume: true },
  { key: 'interview_prep', label: 'Interview Prep', needsResume: true },
  { key: 'company_research', label: 'Company Research', needsResume: false },
  { key: 'resume_improvement', label: 'Resume Improvement', needsResume: true },
  { key: 'referral_search', label: 'Find Referral Contacts', needsResume: false },
  { key: 'referral_message', label: 'Referral Message', needsResume: true },
] as const
export type FeatureKey = (typeof FEATURES)[number]['key']

// Mirrors feature_service.py's _BUNDLED_FEATURES exactly — these four are
// generated together in one LLM call (POST /features/all/{job_id});
// referral_search/referral_message stay single-feature calls, see that
// constant's docstring on the backend for why.
export const BUNDLED_FEATURES: FeatureKey[] = ['cover_letter', 'interview_prep', 'company_research', 'resume_improvement']
