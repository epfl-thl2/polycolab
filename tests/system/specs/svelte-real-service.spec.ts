import { expect, test } from '@playwright/test';
const apiUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';

test('Svelte production journey uses local auth, saved research, a real worker and proposal review', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByLabel('Username', { exact: true }).fill('svelte-researcher');
  await page.getByLabel('Display name', { exact: true }).fill('Svelte Researcher');
  await page.getByLabel('Password', { exact: true }).fill('local-integration-password-only');
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await page.getByRole('button', { name: '+ New project', exact: true }).click();
  await page.getByLabel('Project name').fill('Svelte real research');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+$/);
  const projectId = new URL(page.url()).pathname.split('/')[2];
  await page.getByRole('button', { name: 'Add the first object' }).click();
  await page.getByLabel('Title', { exact: true }).fill('Pinned source');
  await page
    .getByLabel('Markdown', { exact: true })
    .fill('A private source for this investigation.');
  await page.getByRole('button', { name: 'Create object', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Pinned source', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await page.getByLabel('Markdown', { exact: true }).fill('A revised private source.');
  await page.getByRole('button', { name: 'Save new version' }).click();
  await expect(page.getByRole('status')).toContainText('Revision 2 saved');
  const profile = await page.request.post(`${apiUrl}/api/v1/gateway/profiles`, {
    data: {
      display_name: 'Local deterministic provider',
      base_url: 'https://8.8.8.8/v1',
      model_id: 'integration-model',
      api_key: 'local-integration-fixture-key',
    },
  });
  expect(profile.status()).toBe(201);
  const profileId = (await profile.json()).id;
  await page.getByRole('link', { name: 'Sessions', exact: true }).click();
  await page.getByRole('button', { name: 'New session', exact: true }).click();
  await page.getByLabel('AI provider').selectOption(profileId);
  await page.getByText('Context · 0 pinned versions', { exact: true }).click();
  await page.getByRole('checkbox', { name: /Pinned source/ }).check();
  await page
    .getByLabel('Message', { exact: true })
    .fill('Investigate this source and propose findings.');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText('Findings are ready for review.', { exact: true })).toBeVisible({
    timeout: 30000,
  });
  await page.getByRole('link', { name: 'Proposal review', exact: true }).click();
  await page.getByRole('link', { name: 'Deterministic integration findings' }).click();
  await page.getByRole('checkbox').first().check();
  await page.getByRole('button', { name: 'Apply 1 selected decisions' }).click();
  await expect(page.getByRole('status')).toContainText('Selected decisions applied together');
  await page.getByRole('link', { name: 'Research objects', exact: true }).first().click();
  await expect(page.getByRole('link', { name: 'Accepted finding', exact: true })).toBeVisible();
  const publicRead = await page.request.get(`${apiUrl}/public/projects/${projectId}`);
  expect(publicRead.status()).toBe(404);
});
