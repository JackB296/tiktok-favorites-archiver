import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The FastAPI backend serves /api and /media; proxy them in dev so the SPA can
// call same-origin paths. In production FastAPI serves the built dist/ directly.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://localhost:8080",
      "/media": "http://localhost:8080",
    },
  },
  build: { outDir: "dist" },
});
