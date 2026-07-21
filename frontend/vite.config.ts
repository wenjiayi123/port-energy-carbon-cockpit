import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const frontendPort = Number(process.env.FRONTEND_PORT ?? 5173);
const apiTarget = process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8808';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: frontendPort,
    proxy: {
      '/api': apiTarget,
    },
  },
});
