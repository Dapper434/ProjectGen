import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The app calls relative /api paths everywhere. In dev, proxy them to the
    // local Flask backend; in production, a Vercel rewrite (see vercel.json)
    // proxies them to the Tailscale Funnel URL instead. Same-origin in both
    // worlds — no CORS or cross-site cookie configuration needed.
    proxy: {
      '/api': 'http://localhost:5000',
    },
  },
})
