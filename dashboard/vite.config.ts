import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.MEMOS_API_TARGET ?? "http://localhost:8000";

// The Vite dev server proxies /api to the MemOS backend so the dashboard
// never hardcodes a backend origin (docs/Dashboard.md section 6).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
