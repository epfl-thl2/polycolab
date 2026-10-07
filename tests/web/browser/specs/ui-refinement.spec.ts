import { expect, test, type Page } from '../fixtures';
import { claimVersion } from '../../unit/version-fixtures';

async function account(page: Page, signedIn = false) {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: signedIn, username: signedIn ? 'ada' : undefined },
    }),
  );
}

test('Activity URLs preserve filters, aliases and explicit preview through browser history', async ({
  page,
}, info) => {
  await account(page);
  await page.route('**/api/v1/activity**', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.goto('/activity/recent?preview=examples');
  await expect(page).toHaveURL(/\/activity\?preview=examples$/);
  await page.getByRole('combobox', { name: 'Contributor', exact: true }).selectOption('agent');
  await expect(page).toHaveURL(/actor=agent/);
  await expect(page.getByRole('combobox', { name: 'Contribution type' })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('combobox', { name: 'Contributor', exact: true })).toHaveValue(
    'agent',
  );
  await expect(
    page.getByRole('heading', { name: 'Testing a bound for regular graphs' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Active workspaces', exact: true }).click();
  await expect(page).toHaveURL(/view=workspaces/);
  await expect(
    page.getByRole('button', { name: 'Active workspaces', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  const filter = page.getByRole('combobox', { name: 'Time window' });
  const views = page.getByRole('navigation', { name: 'Activity views' });
  const filterBox = await filter.boundingBox();
  const viewsBox = await views.boundingBox();
  expect(
    Math.abs(filterBox!.y + filterBox!.height / 2 - viewsBox!.y - viewsBox!.height / 2),
  ).toBeLessThan(4);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(
    page.getByText('Illustrative order, not a live ranking', { exact: false }),
  ).toBeVisible();
  await page.screenshot({ path: info.outputPath('activity-desktop.png'), fullPage: true });
  await page.goBack();
  await expect(page.getByRole('combobox', { name: 'Contributor', exact: true })).toHaveValue(
    'agent',
  );
  await page.getByRole('button', { name: 'Exit example preview' }).click();
  await expect(page).not.toHaveURL(/preview=/);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'No matching activity' })).toBeVisible();
  await page.goto('/activity?view=unknown&window=year&actor=nobody&preview=no');
  await expect(page).toHaveURL(/\/activity$/);
});

test('People profile deep links restore the directory and focus', async ({ page }, info) => {
  await account(page);
  await page.goto('/people?preview=examples');
  await page.getByRole('searchbox').fill('logic');
  await page.getByRole('button', { name: 'Search people' }).click();
  const trigger = page.getByRole('button', { name: 'View profile for Noor Example' });
  await trigger.click();
  await expect(page).toHaveURL(/profile=example-noor/);
  await expect(page.getByRole('dialog', { name: 'Noor Example' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('people-profile-desktop.png'), fullPage: true });
  await page.keyboard.press('Escape');
  await expect(page).not.toHaveURL(/profile=/);
  await expect(trigger).toBeFocused();
  await expect(page.getByRole('searchbox')).toHaveValue('logic');
  await page.goBack();
  await expect(page.getByRole('dialog', { name: 'Noor Example' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('dialog', { name: 'Noor Example' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: info.outputPath('people-profile-mobile.png'), fullPage: true });
  await page.goto('/people?q=graph&profile=example-noor&preview=examples');
  await expect(page.getByRole('dialog', { name: 'Noor Example' })).toBeVisible();
  await page.goto('/people?profile=missing&preview=examples');
  await expect(page.getByRole('alert')).toContainText('unavailable');
  await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Ada Example' })).toBeVisible();
});

for (const signedIn of [false, true]) {
  test(`navigation fits app, Docs and workspace headers (${signedIn ? 'member' : 'visitor'})`, async ({
    page,
  }, info) => {
    await account(page, signedIn);
    await page.route('**/api/v1/workspaces?**', (route) =>
      route.fulfill({ json: { items: [], next_cursor: null } }),
    );
    for (const path of signedIn ? ['/', '/docs/', '/workspaces'] : ['/', '/docs/']) {
      await page.goto(path);
      await expect(page.getByRole('link', { name: 'Polycolab home' })).toBeVisible();
      for (const width of [1440, 1280, 1024, 900, 768, 390]) {
        await page.setViewportSize({ width, height: 900 });
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
        ).toBeTruthy();
        if (path.startsWith('/docs/')) {
          await expect(
            page.getByRole('navigation', { name: 'Documentation header', exact: true }),
          ).toBeVisible();
          continue;
        }
        if (width >= 900) {
          const nav = page.getByRole('navigation', { name: 'Main navigation' });
          await expect(nav).toBeVisible();
          await expect(nav.getByRole('link', { name: 'Library' })).toBeVisible();
          await expect(nav.getByRole('link', { name: 'Chat Planned' })).toBeVisible();
          const sections = await page
            .locator(
              '.product-brand, .product-breadcrumb, .product-header-search, .product-navigation, .product-header-account',
            )
            .evaluateAll((elements) =>
              elements
                .map((element) => element.getBoundingClientRect())
                .filter((box) => box.width > 0 && box.height > 0)
                .map((box) => ({ left: box.left, right: box.right }))
                .sort((a, b) => a.left - b.left),
            );
          for (let index = 1; index < sections.length; index += 1)
            expect(sections[index].left).toBeGreaterThanOrEqual(sections[index - 1].right - 1);
        } else
          await expect(
            page.getByRole('button', { name: 'Open navigation and account menu' }),
          ).toBeVisible();
      }
      if (path === '/')
        await page.screenshot({ path: info.outputPath('home-mobile.png'), fullPage: true });
    }
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'Docs', exact: true })).toHaveAttribute(
      'href',
      '/docs/',
    );
    await page.getByRole('button', { name: 'Open Docs menu' }).click();
    await expect(page.getByRole('menuitem', { name: 'Getting started' })).toHaveAttribute(
      'href',
      '/docs/getting-started/',
    );
    await expect(page.getByRole('menuitem', { name: 'Developers' })).toHaveAttribute(
      'href',
      '/docs/developers/',
    );
    await page.keyboard.press('Escape');
    await page.goto('/about');
    await expect(page.getByRole('heading', { name: 'About' })).toBeVisible();
  });
}

test('homepage restores result type and renders math without raw markup', async ({
  page,
}, info) => {
  await account(page);
  await page.route('**/api/v1/discovery?*', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            catalogue_entry_id: 'entry',
            object_version: claimVersion({
              id: 'rev',
              content: {
                title: 'Spectral bound',
                content_md: 'A **spectral** bound on $\\lambda_2$.\n\n$$x^2 + y^2$$',
                assumptions_md: 'None stated',
                reported_outcome: null,
                explanation_md: null,
              },
            }),
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.route('**/api/v1/workspaces?*', (route) =>
    route.fulfill({
      json: {
        items: [{ id: 'demo', name: 'Spectral gaps', description: 'Graphs and bounds' }],
        next_cursor: null,
      },
    }),
  );
  await page.goto('/search?q=spectral&type=research');
  await expect(page).toHaveURL(/\/\?q=spectral&type=research$/);
  await expect(page.getByRole('region', { name: 'Workspace results' })).toHaveCount(0);
  await expect(page.locator('.search-excerpt .katex').first()).toBeVisible();
  await expect(page.locator('.search-excerpt mark')).toHaveText('spectral');
  await page
    .getByRole('navigation', { name: 'Search result types' })
    .getByRole('link', { name: 'Workspaces' })
    .click();
  await expect(page).toHaveURL(/type=workspaces/);
  await page.reload();
  await expect(page.getByRole('region', { name: 'Research results' })).toHaveCount(0);
  await page.goBack();
  await expect(page.getByRole('region', { name: 'Research results' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('home-results-desktop.png'), fullPage: true });
});
