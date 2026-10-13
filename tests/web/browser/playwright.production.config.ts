import { resolve } from 'node:path';
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './specs',
  metadata: { productionBuild: true },
  reporter: [['list'], ['json', { outputFile: '../../test-results/production-report.json' }]],
  testMatch: [
    'library.spec.ts',
    'application-configuration.spec.ts',
    'svelte-project.spec.ts',
    'profiles.spec.ts',
    'profile-design.spec.ts',
    'm1-commons.spec.ts',
    'proposal-workflow.spec.ts',
    'agent-session-workflow.spec.ts',
    'research-workflow.spec.ts',
    'discovery-states.spec.ts',
  ],
  timeout: 30000,
  use: { baseURL: 'http://127.0.0.1:4183', trace: 'retain-on-failure' },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js preview --host 127.0.0.1 --port 4183',
    cwd: resolve(__dirname, '../../../src/web'),
    gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
    url: 'http://127.0.0.1:4183',
    reuseExistingServer: false,
  },
});
