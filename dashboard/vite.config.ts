import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

// In dev, /api goes to the bridge. From your computer: `ssh -N -L 8890:127.0.0.1:8890 <your VM>`, then
// `BRIDGE_DEV_LOGIN=you@example.com npm run dev` (the tunnel skips tailscale serve, so the proxy adds the identity it would add).
// On the VM the bridge serves dist/ itself, so the built page calls /api on its own origin.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      proxy: {
        '/api': {
          target: env.BRIDGE_URL ?? 'http://127.0.0.1:8890',
          changeOrigin: true,
          headers: env.BRIDGE_DEV_LOGIN ? { 'Tailscale-User-Login': env.BRIDGE_DEV_LOGIN } : {},
        },
      },
    },
    build: {
      target: 'es2022',
      chunkSizeWarningLimit: 1400,
      rolldownOptions: {
        output: {
          advancedChunks: {
            groups: [{ name: 'three', test: /node_modules[\\/](three|@react-three|postprocessing|maath|three-stdlib)/ }],
          },
        },
      },
    },
  }
})
