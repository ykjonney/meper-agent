import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  // Allow overriding the API/WS proxy target via env var.
  // Docker compose sets VITE_API_TARGET=http://backend:8000; local dev falls back to localhost.
  const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000';
  const wsTarget = apiTarget.replace(/^http/, 'ws');

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // Dev proxy: forward /api and /ws to the meper-agent backend (port 8000),
      // mirroring the umi/Max frontend's .umirc.ts proxy config.
      proxy: {
        '/api/': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/ws/': {
          target: wsTarget,
          ws: true,
          changeOrigin: true,
        },
      },
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modify—file watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
    },
  };
});
