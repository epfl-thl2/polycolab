import { resolve } from 'node:path';
import { defineConfig } from '@playwright/test';

const port = Number(process.env.E2E_PORT ?? '5173');
const baseURL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: './specs',
  timeout: 30_000,
  use: { baseURL, trace: 'retain-on-failure' },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${port}`,
        cwd: resolve(__dirname, '../../../src/web'),
        gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
        reuseExistingServer: false,
        url: `${baseURL}/`,
      },
});
