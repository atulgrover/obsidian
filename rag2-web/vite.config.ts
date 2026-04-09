import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      '/api/lightrag': {
        target: 'http://lightrag:8020',
        rewrite: (path) => path.replace(/^\/api\/lightrag/, ''),
      },
      '/vault': 'http://vault-pipeline:5004',
      '/lightrag': 'http://vault-pipeline:5004',
    },
  },
})