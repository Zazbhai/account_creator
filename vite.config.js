import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Load environment variables from .env file
// Vite automatically loads .env files, but we can also use loadEnv for explicit loading
export default defineConfig(({ mode }) => {
  // Load env file based on `mode` in the current working directory.
  const env = loadEnv(mode, process.cwd(), '')

  // For tunneling (ngrok, etc.), set VITE_BACKEND_URL to your tunneled backend URL
  // Example: VITE_BACKEND_URL=https://xyz789.ngrok-free.app
  const FRONTEND_PORT = parseInt(env.VITE_FRONTEND_PORT || process.env.VITE_FRONTEND_PORT || '7333', 10)
  const BACKEND_URL = env.VITE_BACKEND_URL || process.env.VITE_BACKEND_URL || 'http://localhost:6333'
  const ALLOWED_HOSTS = (env.VITE_ALLOWED_HOSTS || process.env.VITE_ALLOWED_HOSTS || '')
    ? (env.VITE_ALLOWED_HOSTS || process.env.VITE_ALLOWED_HOSTS).split(',').map(h => h.trim())
    : []

  // Log configuration on startup
  console.log('🚀 Vite Configuration:')
  console.log(`   Frontend Port: ${FRONTEND_PORT}`)
  console.log(`   Backend URL: ${BACKEND_URL}`)
  console.log(`   Allowed Hosts: ${ALLOWED_HOSTS.length > 0 ? ALLOWED_HOSTS.join(', ') : 'none'}`)
  console.log('')

  return {
    plugins: [react()],
    server: {
      port: FRONTEND_PORT,
      host: '0.0.0.0', // Listen on all interfaces for tunnel access
      strictPort: false, // Allow port change if occupied
      allowedHosts: ALLOWED_HOSTS.length > 0 ? ALLOWED_HOSTS : 'all', // Allow all hosts for Cloudflare Tunnel
      proxy: {
        '/api': {
          target: BACKEND_URL,
          changeOrigin: true,
          secure: false, // Set to false if using self-signed certificates (common with tunnels)
          timeout: 30000, // 30 second timeout
          configure: (proxy, _options) => {
            // Track last error time per endpoint to throttle logging
            const errorLogTimes = new Map()
            const ERROR_LOG_THROTTLE_MS = 10000 // Only log same endpoint error once per 10 seconds

            proxy.on('error', (err, req, res) => {
              const endpoint = req.url || 'unknown'
              const now = Date.now()
              const lastLogTime = errorLogTimes.get(endpoint) || 0

              // Only log if we haven't logged this endpoint error recently
              if (now - lastLogTime > ERROR_LOG_THROTTLE_MS) {
                errorLogTimes.set(endpoint, now)
                console.error('❌ Proxy error:', err.message)
                console.error('   Request:', req.method, req.url)
                console.error('   Backend URL:', BACKEND_URL)
                console.error('   Make sure the backend is running and accessible at:', BACKEND_URL)
                console.error('   (This error will be throttled for 10 seconds per endpoint)')
              }

              if (!res.headersSent) {
                res.writeHead(502, {
                  'Content-Type': 'text/plain'
                })
                res.end('Bad Gateway: Backend connection failed. Check if backend is running.')
              }
            })
            // Removed verbose proxy request logging - only errors are logged
          }
        },
        '/socket.io': {
          target: BACKEND_URL,
          ws: true,
          secure: false, // Set to false if using self-signed certificates
          changeOrigin: true
        }
      }
    },
    build: {
      outDir: 'dist',
      assetsDir: 'assets'
    }
  }
})
