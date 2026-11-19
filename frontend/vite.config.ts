import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on :8000. In dev, Vite proxies /api so the browser sees one origin.
const API = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 900 },
  server: { port: 5173, proxy: { "/api": { target: API, changeOrigin: true } } },
  preview: { port: 4173, proxy: { "/api": { target: API, changeOrigin: true } } },
});
