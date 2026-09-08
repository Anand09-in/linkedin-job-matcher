import createClient from 'openapi-fetch'
import type { paths } from './schema'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** Typed fetch client generated from the backend's own openapi.json
 * (`npm run generate-api`, Phase 7's exit criterion in practice: this file
 * only exists because that schema is stable/documented). Every hook in
 * api/hooks/ goes through this instead of raw fetch, so a backend response
 * shape change becomes a type error here rather than a silent runtime bug. */
export const api = createClient<paths>({ baseUrl: API_BASE_URL })

/** Surfaces FastAPI's error `detail` (a plain string for our hand-raised
 * HTTPExceptions, or a Pydantic validation-error array for a 422) as one
 * readable message — every mutation hook's onError uses this so the UI
 * never has to know the difference. */
export function apiErrorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'detail' in error) {
    const detail = (error as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d)))
        .join('; ')
    }
  }
  return 'Something went wrong — please try again.'
}

/** POST/PUT /resumes use `multipart/form-data` (a PDF file + form fields),
 * which openapi-fetch's default JSON body serializer can't produce — a
 * small raw-fetch escape hatch just for these two calls, still typed
 * against the generated response schemas via the callers in useResumes.ts. */
export async function uploadForm(path: string, method: 'POST' | 'PUT', form: FormData) {
  const res = await fetch(`${API_BASE_URL}${path}`, { method, body: form })
  const data = await res.json().catch(() => undefined)
  if (!res.ok) throw data ?? { detail: res.statusText }
  return data
}
