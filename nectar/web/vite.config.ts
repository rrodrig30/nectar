import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server proxies same-origin `/api/*` to the NECTAR API so the browser makes no cross-origin
// call (the API sets no CORS headers by design). Target and port are environment-driven, never
// hardcoded: NECTAR_API_TARGET points at the running API, NECTAR_WEB_PORT sets the dev port.
// In production the static build is served by nginx, which proxies `/api/` to the API container
// (see nginx.conf) - so the app always talks to a relative `/api` base in both environments.
const apiTarget = process.env.NECTAR_API_TARGET ?? 'http://localhost:8080';
const webPort = Number(process.env.NECTAR_WEB_PORT ?? 5173);

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: webPort,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
