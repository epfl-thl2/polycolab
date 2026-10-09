import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

const workspaceNodeModules = fileURLToPath(new URL('./node_modules/', import.meta.url));

export default defineConfig({
  plugins: [svelte({ configFile: false })],
  resolve: {
    conditions: ['browser'],
    alias: {
      '$app/navigation': fileURLToPath(
        new URL('../../tests/web/unit/fixtures/navigation.ts', import.meta.url),
      ),
      $lib: fileURLToPath(new URL('./src/lib/', import.meta.url)),
      '@testing-library/svelte': `${workspaceNodeModules}@testing-library/svelte`,
      'oidc-client-ts': `${workspaceNodeModules}oidc-client-ts`,
    },
  },
  test: {
    environment: 'jsdom',
    testTimeout: 15_000,
    server: {
      deps: { inline: ['oidc-client-ts'] },
    },
    include: ['../../tests/web/unit/**/*.test.ts'],
    setupFiles: ['../../tests/web/unit/setup.ts'],
  },
});
