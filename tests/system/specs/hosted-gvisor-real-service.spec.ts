import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

test('native gVisor chat completes and survives reload', async ({ page }) => {
  test.skip(process.env.POLYCOLAB_GVISOR_BROWSER !== '1', 'Requires the disposable native runner');
  test.setTimeout(120_000);
  page.setDefaultTimeout(15_000);
  const login = await page.request.post('/auth/login', {
    data: { username: 'admin', password: 'Hosted-test-password-2026!' },
  });
  expect(login.ok()).toBeTruthy();
  const project = await page.request.post('/api/v1/projects', {
    data: { name: 'Native hosted acceptance' },
  });
  expect(project.status()).toBe(201);
  const projectId = (await project.json()).id;
  // Initialize the project's Main worktree before creating its conversation.
  const worktrees = await page.request.get(`/api/v1/projects/${projectId}/worktrees`);
  expect(worktrees.ok()).toBeTruthy();
  expect((await worktrees.json()).some((tree: { branch: string }) => tree.branch === 'main')).toBe(
    true,
  );
  const profile = await page.request.post('/api/v1/gateway/profiles', {
    data: {
      display_name: 'Deterministic Responses',
      base_url: 'https://8.8.8.8/v1',
      model_id: 'gpt-5.4',
      api_key: 'synthetic-provider-key',
    },
  });
  expect(profile.status()).toBe(201);
  const profileId = (await profile.json()).id;
  const validation = await page.request.post(`/api/v1/gateway/profiles/${profileId}/validate`);
  expect(validation.ok()).toBeTruthy();
  await expect
    .poll(
      async () => {
        const response = await page.request.get('/api/v1/agent-capabilities');
        return (await response.json()).hosted_agents;
      },
      { timeout: 60_000 },
    )
    .toBe(true);
  await page.goto(`/projects/${projectId}/sessions/new`);
  await page
    .getByLabel('Message the agent')
    .filter({ visible: true })
    .fill('Summarize the native execution check.');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page).toHaveURL(/\/sessions\/[0-9a-f-]{36}$/);
  await expect(page.getByText('Native gVisor research completed.', { exact: true })).toBeVisible({
    timeout: 60_000,
  });
  await page.reload();
  await expect(page.getByText('Native gVisor research completed.', { exact: true })).toBeVisible();
  const sessionId = new URL(page.url()).pathname.split('/').at(-1);
  await expect
    .poll(async () => {
      const response = await page.request.get(`/api/v1/agent-sessions/${sessionId}/runs`);
      return (await response.json())[0]?.status;
    })
    .toBe('COMPLETED');
  await page.goto(`/projects/${projectId}/files?branch=main`);
  await expect(
    page.getByRole('navigation', { name: 'File tree' }).getByText('native.txt', { exact: true }),
  ).toBeVisible({ timeout: 15_000 });
  await page.goto(`/projects/${projectId}/sessions/${sessionId}`);
  await page.getByRole('tab', { name: 'Agent history', exact: true }).click();
  await page.getByText('Files and run history', { exact: true }).click();
  await page.getByLabel('Files from completed run').selectOption({ index: 1 });
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download Native result.txt', exact: true }).click();
  const download = await downloadEvent;
  expect(await readFile((await download.path())!, 'utf8')).toBe('native result\n');
  // A follow-up must use a fresh sandbox while retaining canonical chat history.
  await page.getByLabel('AI provider').selectOption(profileId);
  await page.getByLabel('Private message', { exact: true }).fill(`Follow up ${randomUUID()}`);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText('Native gVisor research completed.', { exact: true })).toHaveCount(
    2,
    { timeout: 60_000 },
  );
  await expect
    .poll(async () => {
      const response = await page.request.get(`/api/v1/agent-sessions/${sessionId}/runs`);
      const runs: { status: string }[] = await response.json();
      return runs.filter((run) => run.status === 'COMPLETED').length;
    })
    .toBe(2);
});
