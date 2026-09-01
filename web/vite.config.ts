import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Proxies /api to the FastAPI app on :8000 so frontend code can call plain
// relative paths -- no CORS to reason about in dev, and no hardcoded host
// baked into fetch calls that would need to change for a different setup.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
