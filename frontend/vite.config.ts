import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.NAUTILUS_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: Number(process.env.NAUTILUS_FRONTEND_PORT ?? 5173),
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: Number(process.env.NAUTILUS_FRONTEND_PORT ?? 5173),
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
