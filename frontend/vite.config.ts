import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Configuracion por entorno:
//   - Docker build: nginx proxya /api -> backend:8000, BASE_URL vacio (relative)
//   - Dev local (npm run dev): BASE_URL = http://localhost:8000
//
// Si queres apuntar el dev server a otro backend, exporta VITE_API_BASE_URL
// antes de correr `npm run dev`. Por ejemplo:
//   VITE_API_BASE_URL=http://192.168.1.50:8000 npm run dev

const isDev = process.env.NODE_ENV !== 'production'
const apiBaseUrl = process.env.VITE_API_BASE_URL ?? (isDev ? 'http://localhost:8000' : '')

export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    port: 5173,
    host: true,
    proxy: isDev
      ? {
          '/api': {
            target: apiBaseUrl,
            changeOrigin: true,
            proxyTimeout: 300_000, // 5 min — uploads pueden tardar con embeddings
            timeout: 300_000,
          },
        }
      : undefined,
  },
  build: {
    sourcemap: true,
  },
})
