import { test as base } from '@playwright/test';
export * from '@playwright/test';

export const configuredCapabilities = {
  agent_execution: true,

  verification_submission: true,
  verification_execution: false,
  email_recovery: true,
};

export const test = base.extend({
  context: async ({ context }, use) => {
    await context.route('**/api/v1/config', (route) =>
      route.fulfill({ json: configuredCapabilities }),
    );
    await use(context);
  },
});
