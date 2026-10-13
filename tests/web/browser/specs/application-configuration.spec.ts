import { configuredCapabilities, expect, test, type Page } from '../fixtures';

const projectId = '11111111-1111-4111-8111-111111111111';

async function projectApi(page: Page) {
  const project = {
    id: projectId,
    name: 'Unified research',
    description: '',
    visibility: 'PUBLIC',
    current_user_role: 'OWNER',
    archived_at: null,
    created_at: '2026-09-14T00:00:00Z',
    updated_at: '2026-09-14T00:00:00Z',
  };
  const writes: Record<string, unknown>[] = [];
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: true, username: 'owner', display_name: 'Owner' },
    }),
  );
  await page.route('**/api/v1/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/config') return route.fallback();
    if (['POST', 'PATCH'].includes(request.method())) {
      writes.push(request.postDataJSON());
      Object.assign(project, request.postDataJSON());
      return route.fulfill({ status: request.method() === 'POST' ? 201 : 200, json: project });
    }
    if (path === `/api/v1/projects/${projectId}`) return route.fulfill({ json: project });
    if (path === '/api/v1/projects' || path.endsWith('/members'))
      return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ json: [] });
  });
  return writes;
}

test('configuration failure does not block core project creation or visibility choices', async ({
  page,
}) => {
  const writes = await projectApi(page);
  let requests = 0;
  await page.route('**/api/v1/config', (route) => {
    requests += 1;
    return requests === 1
      ? route.fulfill({ status: 503, json: {} })
      : route.fulfill({ json: configuredCapabilities });
  });
  await page.goto('/projects?scope=member');
  await expect(page.getByRole('button', { name: 'Retry configuration' })).toBeVisible();
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await page.getByLabel('Project name').fill('Private investigation');
  await expect(
    page.getByRole('dialog').getByRole('button', { name: 'Create project', exact: true }),
  ).toBeEnabled();
  await expect(page.getByRole('combobox', { name: 'Visibility', exact: true })).toHaveValue(
    'PUBLIC',
  );
  await page.getByRole('combobox', { name: 'Visibility', exact: true }).selectOption('PRIVATE');
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Create project', exact: true })
    .click();
  await expect.poll(() => writes[0]?.visibility).toBe('PRIVATE');
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}`));
  await page.goBack();
  await page.getByRole('button', { name: 'Retry configuration' }).click();
  await expect(page.getByRole('button', { name: 'Retry configuration' })).toHaveCount(0);
});

test('project creation loads configuration and public visibility remains an explicit choice', async ({
  page,
}) => {
  const writes = await projectApi(page);
  let requests = 0;
  await page.route('**/api/v1/config', (route) => {
    requests += 1;
    return route.fulfill({ json: configuredCapabilities });
  });
  await page.goto('/projects?scope=member');
  await page.getByRole('button', { name: 'New project', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Visibility', exact: true })).toHaveValue(
    'PUBLIC',
  );
  await page.getByLabel('Project name').fill('Private by choice');
  await page.getByRole('combobox', { name: 'Visibility', exact: true }).selectOption('PRIVATE');
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Create project', exact: true })
    .click();
  await expect.poll(() => writes[0]?.visibility).toBe('PRIVATE');
  expect(requests).toBe(1);
});

test('owner visibility changes require confirmation in both directions', async ({ page }) => {
  const writes = await projectApi(page);
  await page.goto(`/projects/${projectId}/settings`);
  for (const visibility of ['PRIVATE', 'PUBLIC']) {
    await page.getByRole('combobox', { name: 'Visibility', exact: true }).selectOption(visibility);
    await page.getByRole('button', { name: 'Save settings', exact: true }).click();
    await expect(page.getByRole('alertdialog')).toBeVisible();
    expect(writes).toHaveLength(visibility === 'PRIVATE' ? 0 : 1);
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.getByRole('button', { name: 'Save settings', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm', exact: true }).click();
    await expect.poll(() => writes.at(-1)?.visibility).toBe(visibility);
    await expect(page.getByText('Settings saved.', { exact: true })).toBeVisible();
  }
});
