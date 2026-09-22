import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Dev: `npm run dev` serves the SPA on :5173 and proxies /api to a locally running panel (python3 panel.py).
// Build: the bundle lands in panel/l4d2panel/static, where the backend serves it at / and /assets.
export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://127.0.0.1:8080' } },
  build: { outDir: '../panel/l4d2panel/static', emptyOutDir: true },
})
