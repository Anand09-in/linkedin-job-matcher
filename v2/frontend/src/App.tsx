import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router'
import { Toaster } from '@/components/Toaster'
import { router } from '@/router'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // No retries by default: this is a local single-user tool talking to
      // one backend on the same machine, not a flaky public API — a failed
      // request is almost always a real 4xx/5xx (caught live: a query with
      // a bad param retried once before finally showing its error, making
      // a real bug look like a slow load instead of an immediate failure).
      retry: false,
      staleTime: 10_000,
    },
  },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>
  )
}

export default App
