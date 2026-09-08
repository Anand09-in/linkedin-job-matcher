import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0', // required to be reachable from outside the Docker container
    port: 5173,
    strictPort: true,
    // Vite's dev server rejects requests whose Host header it doesn't
    // recognize (DNS-rebinding protection) — 'frontend' is this container's
    // own name on the Compose network, needed for host-to-host checks like
    // Phase 8's Playwright verification script running from the worker
    // container (http://frontend:5173, not localhost).
    allowedHosts: ['localhost', 'frontend'],
  },
})
