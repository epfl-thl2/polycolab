import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './local',
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: { baseURL: process.env.LOCAL_MODE_URL, trace: 'retain-on-failure' },
});
