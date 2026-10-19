import { expect, test } from '../fixtures';

test('retired global Chat shows page not found without loading conversations', async ({ page }) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  const chatRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/v1/chat/'))
      chatRequests.push(request.url());
  });
  await page.goto('/chat');
  await expect(page).toHaveTitle('Page not found · Polycolab');
  await expect(page.getByRole('heading', { name: 'Page not found', exact: true })).toBeVisible();
  await expect(page.locator('a[href="/chat"]')).toHaveCount(0);
  await expect(page.getByRole('textbox')).toHaveCount(0);
  expect(chatRequests).toEqual([]);
});
