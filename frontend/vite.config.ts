import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard calls the backend directly (CORS is enabled there), so no proxy is needed.
// Set VITE_API_BASE_URL in frontend/.env to point at a different backend.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
})
