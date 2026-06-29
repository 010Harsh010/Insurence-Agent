import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
const backendTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5999,
    proxy: {
      '/chat':        { target: backendTarget, changeOrigin: true },
      '/upload':      { target: backendTarget, changeOrigin: true },
      '/health':      { target: backendTarget, changeOrigin: true },
      '/updateClaim': { target: backendTarget, changeOrigin: true },
      '/resetDB':     { target: backendTarget, changeOrigin: true },
      '/addPolicy':   { target: backendTarget, changeOrigin: true },
      '/member':      { target: backendTarget, changeOrigin: true },
      '/test':        { target: backendTarget, changeOrigin: true },
    },
  },
})
