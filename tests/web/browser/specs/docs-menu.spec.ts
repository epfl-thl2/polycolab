import { expect, test } from '../fixtures';
import { mockProfiles } from '../helpers/profiles';

test('Docs links to its index and exposes the main documentation routes', async ({
  page,
}, info) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  await page.goto('/');
  const docsLink = page.getByRole('link', { name: 'Docs', exact: true });
  await expect(docsLink).toHaveAttribute('href', '/docs/');
  const trigger = page.getByRole('button', { name: 'Open Docs menu', exact: true });
  await expect(trigger).toHaveCSS('border-top-width', '0px');
  await expect(trigger).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await docsLink.hover();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await expect(
    page.getByRole('menuitem', { name: 'Getting started', exact: true }),
  ).toHaveAttribute('href', '/docs/getting-started/');
  await expect(page.getByRole('menuitem', { name: 'Developers', exact: true })).toHaveAttribute(
    'href',
    '/docs/developers/',
  );
  await page.screenshot({ path: info.outputPath('docs-menu.png') });
  await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await trigger.click();
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await trigger.click();
  // Finish the previous menu's exit transition before checking outside dismissal.
  await expect(page.getByRole('menuitem', { name: 'Developers', exact: true })).toBeVisible();
  await page.waitForTimeout(150);
  await page.getByRole('heading', { level: 1 }).click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await docsLink.click();
  await expect(page).toHaveURL(/\/docs\/$/);
  await expect(page.getByRole('heading', { name: 'Index', exact: true })).toBeVisible();
  await expect(
    page.getByRole('navigation', { name: 'Documentation header', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sign in', exact: true })).toHaveCount(0);
});

for (const mobile of [false, true]) {
  test(`account menu stays usable in the app (${mobile ? 'mobile' : 'desktop'})`, async ({
    page,
  }, info) => {
    await mockProfiles(page, true);
    await page.setViewportSize({ width: mobile ? 390 : 1280, height: 900 });
    await page.goto('/');
    const trigger = page.getByRole('button', {
      name: mobile ? 'Open navigation and account menu' : 'Open account menu for Ada',
      exact: true,
    });
    await expect(trigger).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await trigger.click();
    await expect(page.getByRole('menuitem', { name: 'Profile', exact: true })).toBeVisible();
    await expect(
      page.getByRole('menuitem', { name: 'Agent connections', exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('menuitem', { name: 'Password and authentication', exact: true }),
    ).toHaveAttribute('href', '/settings/security');
    await page.screenshot({ path: info.outputPath('home-account.png') });
    await trigger.click();
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await trigger.click();
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
    await expect(trigger).toHaveAttribute('aria-expanded', 'false');
    await trigger.click();
    await page.getByRole('menuitem', { name: 'Profile', exact: true }).click();
    await expect(page).toHaveURL('/profile/ada');
  });
}
