import { defineConfig } from '@playwright/test';

const baseURL = process.env.POLYCOLAB_INTEGRATION_WEB_URL ?? 'http://127.0.0.1:13000';

export default defineConfig({
  testDir: './specs',
  timeout: 45_000,
  workers: 1,
  use: { baseURL, trace: 'retain-on-failure' },
});
