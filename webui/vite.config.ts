import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import vuetify from 'vite-plugin-vuetify'

export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  base: './',
  build: {
    // 构建产物直接输出到插件的视图目录，AstrBot 自动加载 views/settings/index.html
    outDir: fileURLToPath(new URL('../views/settings', import.meta.url)),
    emptyOutDir: true,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        // 禁用代码分割，尽量打成单文件，避免 iframe 内相对路径/CORS 问题
        inlineDynamicImports: true,
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})