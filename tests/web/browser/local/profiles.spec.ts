import { expect, test } from '@playwright/test';

test('real local profiles resolve personal identity and show public research by username', async ({
  page,
  baseURL,
}) => {
  test.skip(!baseURL, 'Run through the local-mode smoke runner.');
  const username = `profile${Date.now()}`;
  await page.goto('/signup');
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill('profile-browser-test-password');
  await page.getByLabel('Confirm password', { exact: true }).fill('profile-browser-test-password');
  await page.getByRole('main').getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page).toHaveURL('/projects');
  await page.goto('/profile');
  await expect(page).toHaveURL(`/profile/${username}`);
  await expect(page.getByRole('heading', { name: 'No public contributions loaded' })).toBeVisible();
  const headers = { Origin: baseURL! };
  const projectResponse = await page.request.post('/api/v1/projects', {
    headers,
    data: { name: 'Profile browser research', visibility: 'PUBLIC' },
  });
  expect(projectResponse.status()).toBe(201);
  const project = await projectResponse.json();
  const contribution = await page.request.post('/api/v1/objects', {
    headers: { ...headers, 'Idempotency-Key': `claim-${username}` },
    data: {
      destination: { kind: 'project', project_id: project.id },
      snapshot: {
        kind: 'STATEMENT',
        content: {
          title: 'Profile browser claim',
          content_md: 'Public research.',
          assumptions_md: 'None stated',
          reported_outcome: null,
          explanation_md: null,
        },
        structural_relationships: [],
        change_summary: 'Public researcher directory fixture',
      },
    },
  });
  expect(contribution.status(), await contribution.text()).toBe(201);
  await page.goto('/profile?type=research#history');
  await expect(page).toHaveURL(`/profile/${username}?type=research#history`);
  await expect(
    page
      .getByRole('region', { name: 'Public contributions', exact: true })
      .getByText('Profile browser claim', { exact: true }),
  ).toBeVisible();
  const identity = await (await page.request.get('/api/v1/users/me')).json();
  expect((await page.request.get(`/api/v1/profile/${identity.id}`)).status()).toBe(404);
  expect((await page.request.get(`/api/v1/profile/${identity.id}/activity`)).status()).toBe(404);
  const visitor = await page.context().browser()!.newContext({ baseURL });
  try {
    const anonymous = await visitor.newPage();
    expect((await visitor.request.get(`/api/v1/profile/${identity.id}`)).status()).toBe(404);
    await anonymous.goto(`/profile/${identity.id}`);
    await expect(
      anonymous.getByRole('heading', { name: 'Could not load contributions' }),
    ).toBeVisible();
    await anonymous.goto(`/profile/${username}`);
    await expect(anonymous.getByRole('heading', { name: username, exact: true })).toBeVisible();
    await expect(
      anonymous
        .getByRole('region', { name: 'Public contributions', exact: true })
        .getByText('Profile browser claim', { exact: true }),
    ).toBeVisible();
    await anonymous.reload();
    await expect(
      anonymous
        .getByRole('region', { name: 'Public contributions', exact: true })
        .getByText('Profile browser claim', { exact: true }),
    ).toBeVisible();
    const hidden = await page.request.patch(`/api/v1/projects/${project.id}`, {
      headers,
      data: { visibility: 'PRIVATE' },
    });
    expect(hidden.status()).toBe(200);
    expect((await visitor.request.get(`/api/v1/profile/${username}`)).status()).toBe(404);
    await anonymous.goto(`/profile/${username}`);
    await expect(
      anonymous.getByRole('heading', { name: 'Could not load contributions' }),
    ).toBeVisible();
    expect((await visitor.request.get('/api/v1/profiles')).status()).toBe(404);
    await page.goto(`/profile/${username}`);
    await expect(
      page.getByRole('heading', { name: 'No public contributions loaded' }),
    ).toBeVisible();
  } finally {
    await visitor.close();
  }
});
