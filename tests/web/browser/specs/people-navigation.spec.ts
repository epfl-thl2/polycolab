import { expect, test } from '../fixtures';

test('People supports example discovery and profile inspection on desktop and mobile', async ({
  page,
}) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  await page.goto('/people');
  await expect(page.getByRole('heading', { name: 'People', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Preview with examples' }).click();
  await page.getByRole('searchbox').fill('graph');
  await page.getByRole('button', { name: 'Search people' }).click();
  await expect(page.getByRole('heading', { name: 'Noor Example' })).toHaveCount(0);
  await page.getByRole('button', { name: 'View profile for Ada Example' }).click();
  await expect(page.getByRole('dialog', { name: 'Ada Example' })).toContainText('Spectral gaps');
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  for (const width of [1280, 1150, 1024, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBeTruthy();
  }
  await page.getByRole('button', { name: 'Open navigation and account menu' }).click();
  await expect(page.getByRole('menuitem', { name: /People/ })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Ada Example', exact: true })).toBeVisible();
});
