import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8081', changeOrigin: true, rewrite: path => path.replace(/^\/api/, '') },
      '/agent': { target: 'http://127.0.0.1:8000', changeOrigin: true, rewrite: path => path.replace(/^\/agent/, '') },
      '/v1': { target: 'http://127.0.0.1:8081', changeOrigin: true },
    },
  },
})
