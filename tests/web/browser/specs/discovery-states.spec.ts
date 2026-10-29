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
    if (/\/api\/v1\/(projects|library|history)/.test(request.url()))
      researchRequests.push(request.url());
  });
  for (const path of [
    '/demo',
    '/demo/finite-tree-colorings',
    '/projects/demo',
    '/projects/demo/settings',
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
