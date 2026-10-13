import { expect, test, type Page } from '../fixtures';

async function account(page: Page, initiallySignedIn = false) {
  let signedIn = initiallySignedIn;
  await page.route('**/auth/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,

          verification_submission: true,
          verification_execution: false,
          email_recovery: true,
        },
      });
    if (path === '/auth/login' || path === '/auth/register') signedIn = true;
    if (path === '/auth/logout') signedIn = false;
    return route.fulfill({
      json:
        path === '/auth/config'
          ? { mode: 'local', registration_mode: 'open' }
          : { authenticated: signedIn, username: 'ada', display_name: 'Ada Lovelace' },
    });
  });
  await page.route('**/api/v1/catalogue', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route(new RegExp('/api/v1/account/agents(?:\\?.*)?$'), (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route(new RegExp('/api/v1/projects(?:\\?.*)?$'), (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
}

for (const mode of ['signin', 'signup'] as const) {
  test(`${mode} returns to the original journey and preserves it when switching forms`, async ({
    page,
  }) => {
    await account(page);
    await page.goto('/library');
    await page.getByRole('banner').getByRole('link', { name: 'Sign in', exact: true }).click();
    await expect(page).toHaveURL(/\/signin\?returnTo=%2Flibrary$/);
    await page.getByRole('main').getByRole('link', { name: 'Sign up', exact: true }).click();
    await expect(page).toHaveURL(/\/signup\?returnTo=%2Flibrary$/);
    if (mode === 'signin')
      await page.getByRole('main').getByRole('link', { name: 'Sign in', exact: true }).click();
    await expect(
      page.getByRole('heading', {
        name: mode === 'signin' ? 'Sign in' : 'Create account',
        exact: true,
      }),
    ).toBeVisible();
    await page.getByLabel('Username', { exact: true }).fill('ada');
    await page.getByLabel('Password', { exact: true }).fill('a-long-test-password');
    if (mode === 'signup')
      await page.getByLabel('Confirm password', { exact: true }).fill('a-long-test-password');
    await page
      .getByRole('main')
      .getByRole('button', { name: mode === 'signup' ? 'Create account' : 'Sign in', exact: true })
      .click();
    await expect(page).toHaveURL(/\/library$/);
    await expect(
      page.getByRole('button', { name: 'Open account menu for Ada Lovelace' }),
    ).toBeVisible();
  });
}

test('already signed-in account entry rejects external return destinations', async ({ page }) => {
  await account(page, true);
  await page.goto('/signin?returnTo=https%3A%2F%2Fexternal.example');
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
});

test('Docs index keeps its anchor and focused navigation', async ({ page }) => {
  await page.goto('/docs#index');
  await expect(page).toHaveURL(/\/docs#index$/);
  await expect(page.getByRole('heading', { name: 'Index', exact: true })).toBeVisible();
  await expect(
    page.getByRole('navigation', { name: 'Documentation sections', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sign in', exact: true })).toHaveCount(0);
});

test('account shortcuts are reachable on desktop and a short mobile screen', async ({
  page,
}, info) => {
  await account(page, true);
  for (const width of [1280, 360]) {
    await page.setViewportSize({ width, height: 640 });
    await page.goto('/settings');
    const trigger = page.getByRole('button', {
      name:
        width === 360 ? 'Open navigation and account menu' : 'Open account menu for Ada Lovelace',
    });
    await trigger.click();
    const menu = page.getByRole('menu');
    await expect(menu.getByText('@ada')).toBeVisible();
    const bounds = await menu.boundingBox();
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(640);
    const security = page.getByRole('menuitem', {
      name: 'Password and authentication',
      exact: true,
    });
    await security.scrollIntoViewIfNeeded();
    await security.click();
    await expect(
      page.getByRole('region', { name: 'Password and authentication', exact: true }),
    ).toBeVisible();
    await trigger.click();
    await page.getByRole('menuitem', { name: 'Sign out', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: info.outputPath(`account-menu-${width}.png`) });
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    );
  }
});

test('agent connection errors offer a retry and a real next step for new contributors', async ({
  page,
}) => {
  await account(page, true);
  let fail = true;
  await page.route(new RegExp('/api/v1/account/agents(?:\\?.*)?$'), (route) =>
    route.fulfill(
      fail
        ? { status: 503, json: { detail: 'Unavailable' } }
        : { json: { items: [], next_cursor: null } },
    ),
  );
  await page.goto('/agents');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByText(/No agents yet/)).toHaveCount(0);
  fail = false;
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByText(/No agents yet/)).toBeVisible();
  await page.getByRole('link', { name: 'Open your projects' }).click();
  await page.getByRole('button', { name: 'New project' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
});
