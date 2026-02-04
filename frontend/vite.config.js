import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    // 允许你的 Cloudflare 域名
    allowedHosts: [
      'note.wulala.dpdns.org',
      'noteapi.wulala.dpdns.org'
    ],
    // 👇👇👇 关键修正：解决白屏和 Protocol Error 👇👇👇
    hmr: {
      clientPort: 443, // 告诉浏览器："我是通过 HTTPS (443) 来的，别去连 5173"
    }
  }
})