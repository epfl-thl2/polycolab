import { expect, test } from '../fixtures';

test('discovery pages share heading geometry, meaningful titles and accessible footer links', async ({
  page,
}, info) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  await page.route('**/api/v1/discovery?*', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route('**/api/v1/projects?*', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    let origin: { x: number; y: number } | undefined;
    for (const [path, title] of [
      ['/', 'Home'],
      ['/activity', 'Activity'],
      ['/people', 'People'],
      ['/chat', 'Chat'],
    ]) {
      await page.goto(path);
      await expect(page).toHaveTitle(`${title} · Polycolab`);
      const heading = page.locator('main h1');
      await expect(heading).toBeVisible();
      const box = (await heading.boundingBox())!;
      if (path === '/people' || path === '/chat') {
        const description = (await page.locator('.discovery-heading > p').boundingBox())!;
        expect(description.y - box.y - box.height).toBeCloseTo(12, 0);
        if (origin) {
          expect(box.x).toBeCloseTo(origin.x, 0);
          expect(box.y).toBeCloseTo(origin.y, 0);
        } else origin = box;
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        width,
      );
      for (const link of await page.getByRole('contentinfo').getByRole('link').all())
        expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(width <= 700 ? 44 : 28);
      await page.screenshot({ path: info.outputPath(`${title}-${width}.png`), fullPage: true });
    }
  }
  await page.goto('/?q=spectral');
  await expect(page).toHaveTitle('Results for “spectral” · Polycolab');
  await page.goto('/people');
  await page.goBack();
  await expect(page).toHaveTitle('Results for “spectral” · Polycolab');
  await page.goto('/404');
  await expect(page).toHaveTitle('Page not found · Polycolab');
});
