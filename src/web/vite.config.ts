import { docsSite } from '../../docs-site/vite-plugin.mjs';
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv } from 'vite';
import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';
import process from 'node:process';
export default defineConfig(({ mode }) => {
  const environment = loadEnv(
    mode,
    fileURLToPath(new URL('../../deploy/docker/', import.meta.url)),
    'POLYCOLAB_',
  );
  const apiTarget = environment.POLYCOLAB_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  return {
    cacheDir: process.env.POLYCOLAB_SVELTE_OUT_DIR
      ? `${process.env.POLYCOLAB_SVELTE_OUT_DIR}/vite`
      : undefined,
    optimizeDeps: {
      // These dependencies are reached through lazy workspace views. Prebundle
      // them before navigation so discovery does not invalidate active imports.
      include: [
        'monaco-editor',
        'unified',
        'remark-parse',
        'remark-math',
        'remark-rehype',
        'rehype-sanitize',
        'rehype-katex',
        'rehype-stringify',
      ],
    },
    plugins: [
      {
        name: 'polycolab-local-api-reference',
        apply: 'serve',
        configureServer(server) {
          server.middlewares.use('/api/openapi.json', async (_request, response, next) => {
            try {
              const schema = await readFile(new URL('./openapi.json', import.meta.url));
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
