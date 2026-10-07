import { expect, test } from '../fixtures';

test('footer presents two rows and links feedback to the generic missing page', async ({
  page,
}, info) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    const footer = page.getByRole('contentinfo');
    await expect(footer.getByText('Local build', { exact: true })).toBeVisible();
    await expect(footer.getByRole('navigation')).toContainText('About Documentation API reference');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    );
    await footer.screenshot({ path: info.outputPath(`footer-${width}.png`) });
    await footer.getByRole('link', { name: 'Feedback / Report an issue' }).click();
    await expect(page).toHaveURL(/\/404$/);
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
    await page.reload();
    await page.getByRole('link', { name: 'Return home', exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
  }
});
