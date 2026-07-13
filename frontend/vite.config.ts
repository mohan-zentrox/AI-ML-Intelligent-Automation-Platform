import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Project Synapse frontend build config.
// VITE_API_BASE_URL (see .env.example at repo root) controls where the SPA
// sends API requests; defaults to the docker-compose backend service.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
});
