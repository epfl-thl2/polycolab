import { expect, test } from '../fixtures';

test('retired demo URLs show page recovery without requiring sign-in', async ({ page }) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  const researchRequests: string[] = [];
  page.on('request', (request) => {
    if (/\/api\/v1\/(workspaces|library|history)/.test(request.url()))
      researchRequests.push(request.url());
  });
  for (const path of [
    '/demo',
    '/demo/finite-tree-colorings',
    '/workspaces/demo',
    '/workspaces/demo/settings',
    '/library/demo',
    '/library/demo/example-1',
    '/profile/demo',
  ]) {
    await page.goto(path);
    await expect(page.getByRole('heading', { name: 'Page not found', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Return home', exact: true })).toHaveAttribute(
      'href',
      '/',
    );
  }
  expect(researchRequests).toEqual([]);
});

test('Library and public workspace errors recover without false empty states or lost searches', async ({
  page,
}, info) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  let failLibrary = true;
  await page.route('**/api/v1/library**', (route) =>
    route.fulfill(
      failLibrary
        ? { status: 503, json: { detail: 'Temporarily unavailable' } }
        : { json: { items: [], next_cursor: null } },
    ),
  );
  let failWorkspaces = false;
  const queries: string[] = [];
  await page.route('**/api/v1/workspaces**', (route) => {
    queries.push(new URL(route.request().url()).searchParams.get('q') ?? '');
    return route.fulfill(
      failWorkspaces
        ? { status: 503, json: { detail: 'Temporarily unavailable' } }
        : { json: { items: [], next_cursor: null } },
    );
  });
  await page.goto('/library');
  await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Could not load Library');
  await expect(
    page.getByRole('heading', { name: 'The Library is ready for its first entry' }),
  ).toHaveCount(0);
  failLibrary = false;
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'The Library is ready for its first entry' }),
  ).toBeVisible();
  await page.screenshot({ path: info.outputPath('library-empty.png') });
  await page.goto('/workspaces?scope=public');
  await expect(page.getByRole('heading', { name: 'No workspaces yet' })).toBeVisible();
  failWorkspaces = true;
  await page.getByRole('searchbox', { name: 'Search' }).fill('spectral');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'No matching workspaces' })).toHaveCount(0);
  failWorkspaces = false;
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'No matching workspaces' })).toBeVisible();
  expect(queries.at(-1)).toBe('spectral');
  await expect(page.getByRole('searchbox')).toHaveValue('spectral');
  await page.getByRole('button', { name: 'Clear search' }).click();
  await expect(page.getByRole('heading', { name: 'No workspaces yet' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: info.outputPath('workspaces-empty-mobile.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
