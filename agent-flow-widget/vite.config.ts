import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';

export default defineConfig({
  plugins: [preact()],
  build: {
    // Widget 构建为 IIFE 单文件，所有静态资源（含 logo png）必须内联为 base64，
    // 否则第三方嵌入时引用外部资源会 404。
    assetsInlineLimit: 100000,
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
