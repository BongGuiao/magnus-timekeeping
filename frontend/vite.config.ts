import { readFileSync } from 'node:fs'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8000'
  const packageJson = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as {
    version: string
  }

  return {
    define: {
      'import.meta.env.VITE_APP_VERSION': JSON.stringify(env.VITE_APP_VERSION || packageJson.version),
    },
    plugins: [react(), tailwindcss()],
    server: {
      host: '0.0.0.0', // Expose to Docker network
      port: 3000,
      strictPort: true,
      allowedHosts: ['frontend', 'localhost', '.trycloudflare.com', 'mbsione.com', 'www.mbsione.com'], // Allow temporary HTTPS tunnels for mobile geolocation testing
      proxy: {
        '^/(api|auth|enrollment|attendance|companies|org-units|operational-groups|locations|geofences|employees|employment-assignments|employee-skills|holiday-calendars|holidays|announcements|leave-types|employee-entitlements|leave-applications|leave-ledger|payroll|payroll-groups|payroll-cutoffs|schedule-templates|employee-schedule-assignments|schedule-uploads|my-schedule-assignments|emergency-schedule-requests|rest-day-patterns|devices|psgc|transactions|docs|redoc|openapi\\.json)(/|$)': {
          target: backendTarget,
          changeOrigin: true,   
        },
      },
      watch: {
        usePolling: true, // Needed for Hot Module Reload (HMR) inside Docker volumes
      },
    },
  }
})