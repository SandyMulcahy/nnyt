import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // In development the React app runs on :5173 and Flask on :8080.
    // Proxying keeps the frontend code identical to production: it always
    // calls same-origin /api/... paths.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
      },
    },
  },
});
