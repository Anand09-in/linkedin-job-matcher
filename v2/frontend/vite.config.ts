import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // required to be reachable from outside the Docker container
    port: 5173,
    strictPort: true,
  },
})
