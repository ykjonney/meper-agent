import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    host: true, // 监听 0.0.0.0：orca 端口转发代理从网桥侧连入也能到达
    port: 3002,
    proxy: {
      // 与 frontend-studio 同一后端：REST + SSE 走 /api，静态文件走 /files
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/files': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
});
