import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';

export default defineConfig({
  plugins: [preact()],
  build: {
    lib: {
      entry: 'src/index.tsx',
      name: 'AgentChat',
      fileName: () => 'agent-chat.js',
      formats: ['iife'],
    },
    outDir: 'dist',
    sourcemap: false,
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
      },
      format: {
        // 保留 window.AgentChat 赋值
        semicolons: true,
      },
    },
  },
});
