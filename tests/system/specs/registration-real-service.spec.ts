import { expect, test } from '@playwright/test';

const apiUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';
const enabled = process.env.POLYCOLAB_INTEGRATION_REGISTRATION === '1';

test.skip(!enabled, 'requires the isolated open-registration system harness');

test('built-in open registration creates an ordinary account and supports login', async ({
  page,
}) => {
  await page.goto('/signin');
  await page.getByLabel('Username', { exact: true }).fill('admin');
  await page.getByLabel('Password', { exact: true }).fill('registration-admin-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Workspaces', exact: true })).toBeVisible();

  const origin = new URL(page.url()).origin;
  const firstLogout = await page.request.post(`${apiUrl}/auth/logout`, {
    headers: { Origin: origin },
  });
  expect(firstLogout.status()).toBe(204);

  await page.goto('/signup');
  await expect(page.getByRole('heading', { name: 'Create your Polycolab account' })).toBeVisible();
  await expect(page.getByLabel('Email')).toHaveCount(0);
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await page.getByLabel('Display name', { exact: true }).fill('New Researcher');
  await page.getByLabel('Username', { exact: true }).fill('new-researcher');
  await page.getByLabel('Password', { exact: true }).fill('new-researcher-password');
  await page.getByLabel('Confirm password').fill('new-researcher-password');

  const sent = page.waitForRequest(
    (request) =>
      request.method() === 'POST' && new URL(request.url()).pathname === '/auth/register',
  );
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  expect((await sent).postDataJSON()).toEqual({
    username: 'new-researcher',
    password: 'new-researcher-password',
    display_name: 'New Researcher',
  });
  await expect(page.getByRole('heading', { name: 'Workspaces', exact: true })).toBeVisible();

  const account = await page.request.get(`${apiUrl}/auth/me`);
  expect(account.status()).toBe(200);
  expect(await account.json()).toMatchObject({
    authenticated: true,
    username: 'new-researcher',
    display_name: 'New Researcher',
    is_admin: false,
  });

  const secondLogout = await page.request.post(`${apiUrl}/auth/logout`, {
    headers: { Origin: origin },
  });
  expect(secondLogout.status()).toBe(204);
  await page.goto('/signin');
  await page.getByLabel('Username', { exact: true }).fill('new-researcher');
  await page.getByLabel('Password', { exact: true }).fill('new-researcher-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Workspaces', exact: true })).toBeVisible();
});
