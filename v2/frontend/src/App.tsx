import { useEffect, useState } from 'react'
import './App.css'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type HealthResponse = {
  status: string
  db: string
  redis: string
  version: string
}

// Phase 0 placeholder: proves frontend -> api connectivity across the Docker
// network before any real pages exist. Phase 8 replaces this file entirely
// with the real app (routing, Job Results, Pipelines manager, etc. per
// plan.md Phase 8 / functional-requirements.md FR-8).
function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then((res) => res.json())
      .then(setHealth)
      .catch((err) => setError(String(err)))
  }, [])

  return (
    <main style={{ fontFamily: 'sans-serif', padding: '2rem' }}>
      <h1>LinkedIn Job Matcher — v2</h1>
      <p>Phase 0 placeholder. Real UI lands in Phase 8.</p>
      <h2>Backend health check ({API_BASE_URL}/health)</h2>
      {error && <p style={{ color: 'crimson' }}>Error: {error}</p>}
      {health && <pre>{JSON.stringify(health, null, 2)}</pre>}
      {!health && !error && <p>Loading…</p>}
    </main>
  )
}

export default App
