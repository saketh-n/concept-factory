import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend origin the dev server proxies to. Override with CF_BACKEND_URL when
// the backend runs on a non-default port (e.g. 8000 is taken).
const backend = process.env.CF_BACKEND_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/concepts": backend,
    },
  },
});
