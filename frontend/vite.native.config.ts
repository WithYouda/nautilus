import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
export default defineConfig({
  root: fileURLToPath(new URL('./native', import.meta.url)),
  plugins: [react()],
  build: { outDir: fileURLToPath(new URL('../native/dist', import.meta.url)), emptyOutDir: true },
})
