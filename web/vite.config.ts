import { docsSite } from '../docs-site/vite-plugin.mjs';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';
export default defineConfig(({ mode }) => {
  const environment = loadEnv(
    mode,
    fileURLToPath(new URL('../deploy/docker/', import.meta.url)),
    'POLYCOLAB_',
  );
  const apiTarget = environment.POLYCOLAB_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  return {
    plugins: [
      {
        name: 'polycolab-local-api-reference',
        apply: 'serve',
        configureServer(server) {
          server.middlewares.use('/api/openapi.json', async (_request, response, next) => {
            try {
              const schema = await readFile(
                new URL('../packages/api-client/openapi.json', import.meta.url),
              );
              response.setHeader('Content-Type', 'application/json');
              response.setHeader('Cache-Control', 'no-store');
              response.end(schema);
            } catch (error) {
              next(error);
            }
          });
        },
      },
      docsSite(),
      tailwindcss(),
      sveltekit(),
    ],
    server: {
      proxy: {
        '/api': apiTarget,
        '/auth': apiTarget,
        '/health': apiTarget,
      },
    },
  };
});
