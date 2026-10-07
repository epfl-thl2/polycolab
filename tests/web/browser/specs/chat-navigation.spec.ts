import { expect, test } from '../fixtures';

for (const signedIn of [false, true]) {
  test(`planned Chat is inspectable for ${signedIn ? 'signed-in' : 'anonymous'} readers`, async ({
    page,
  }) => {
    await page.route('**/auth/**', (route) =>
      route.fulfill({
        json: route.request().url().endsWith('/config')
          ? { mode: 'local' }
          : { authenticated: signedIn, username: signedIn ? 'ada' : undefined },
      }),
    );
    await page.goto('/');
    const navigation = page.getByRole('navigation', { name: 'Main navigation' });
    await expect(navigation.getByRole('link', { name: 'Activity' })).toBeVisible();
    await navigation.getByRole('link', { name: 'Chat Planned' }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole('heading', { name: 'Chat', exact: true })).toBeVisible();
    await expect(page.getByRole('textbox')).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Send message' })).toBeDisabled();
    for (const width of [1280, 1024, 390]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
      ).toBeTruthy();
    }
    await page.getByRole('button', { name: 'Open navigation and account menu' }).click();
    await expect(page.getByRole('menuitem', { name: 'Chat Planned' })).toHaveAttribute(
      'href',
      '/chat',
    );
    await expect(page.getByRole('menuitem', { name: 'Activity' })).toBeVisible();
  });
}
