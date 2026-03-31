import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Access dev server from phone on LAN: http://YOUR_PC_IP:5173
    host: true,
    port: 5173,
    proxy: {
      // Same-origin /api → FastAPI on :8000 (no CORS). Nginx production uses /api too.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, "") || "/",
      },
    },
  },
});
