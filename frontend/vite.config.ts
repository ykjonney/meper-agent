import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      host: '0.0.0.0',
      // HMR settings for Docker
      hmr: {
        host: 'localhost',
      },
      proxy: {
        '/api/': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/ws/': {
          target: apiTarget.replace('http', 'ws'),
          ws: true,
        },
      },
    },
  }
})
