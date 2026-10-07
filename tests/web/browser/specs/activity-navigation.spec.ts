import { expect, test } from '../fixtures';

test.use({ timezoneId: 'Europe/Zurich' });

for (const signedIn of [false, true]) {
  test(`Activity preview works without a backend for ${signedIn ? 'signed-in' : 'anonymous'} readers`, async ({
    page,
  }) => {
    await page.route('**/auth/**', (route) =>
      route.fulfill({
        json: route.request().url().endsWith('/auth/config')
          ? { mode: 'local' }
          : { authenticated: signedIn, username: signedIn ? 'ada' : undefined },
      }),
    );
    await page.route('**/api/v1/activity**', (route) =>
      route.fulfill({ json: { items: [], next_cursor: null } }),
    );
    await page.goto('/');
    await page
      .getByRole('navigation', { name: 'Main navigation' })
      .getByRole('link', { name: /^Activity/ })
      .click();
    await expect(page).toHaveURL(/\/activity$/);
    await expect(page.getByRole('heading', { name: /^Activity/, exact: true })).toHaveClass(
      /\bsr-only\b/,
    );
    await expect(page.getByRole('heading', { name: 'No matching activity' })).toBeVisible();
    await page.goto('/activity?preview=examples');
    await expect(
      page.getByRole('heading', { name: 'Testing a bound for regular graphs' }),
    ).toBeVisible();
    await page.getByRole('combobox', { name: 'Contributor', exact: true }).selectOption('human');
    await expect(
      page.getByRole('heading', { name: 'Testing a bound for regular graphs' }),
    ).toHaveCount(0);
    await page.getByRole('button', { name: 'Active workspaces', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Spectral gaps' })).toBeVisible();
    await expect(page.getByRole('columnheader')).toHaveText([
      'Workspace',
      'Contributors',
      'Submissions',
      'Last submission (local)',
    ]);
    await expect(
      page.getByRole('main').getByRole('button', { name: 'Sign in to Polycolab' }),
    ).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole('heading', { name: /^Activity/, exact: true })).toHaveClass(
      /\bsr-only\b/,
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole('heading', { name: 'Spectral gaps' })).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBeTruthy();
    await page.getByRole('button', { name: 'Open navigation and account menu' }).click();
    await expect(page.getByRole('menuitem', { name: /^Activity/ })).toHaveAttribute(
      'href',
      '/activity',
    );
  });
}

test('recent public submissions replace 50 single-line rows per page and stop at 500', async ({
  page,
}) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  await page.route('**/api/v1/activity?*', (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get('recent')).toBe('true');
    expect(url.searchParams.get('limit')).toBe('50');
    const offset = Number(url.searchParams.get('cursor') ?? 0);
    return route.fulfill({
      json: {
        items: Array.from({ length: 50 }, (_, i) => ({
          id: `event-${offset + i}`,
          submission_number: 1200 - offset - i,
          object_id: `object-${offset + i}`,
          object_version_id: `revision-${offset + i}`,
          title: `Submission ${offset + i + 1}`,
          object_kind: 'STATEMENT',
          action: 'object.created',
          workspace_id: 'public-workspace',
          workspace_name: 'Public mathematics',
          object_version_number: 2,
          actor: { kind: 'human', display_name: 'Ada' },
          occurred_at: '2026-09-15T10:00:00Z',
        })),
        next_cursor: String(offset + 50),
      },
    });
  });
  await page.goto('/activity');
  const rows = page.locator('.submission-row');
  await expect(page.getByRole('columnheader')).toHaveText([
    '#',
    'Contributor',
    'Workspace',
    'Type',
    'Submission',
    'Version',
    'Time (local)',
  ]);
  await expect(page.getByLabel('Contributor legend')).toContainText('Human');
  await expect(rows).toHaveCount(50);
  await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Recent submissions', exact: true })).toHaveCount(
    0,
  );
  await expect(rows.first().getByRole('cell').first()).toHaveText('1200');
  await expect(
    page
      .getByRole('navigation', { name: 'Main navigation' })
      .getByRole('link', { name: 'Activity', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Time window' })).toHaveCount(0);
  await expect(rows.first()).toContainText('Public mathematics');
  await expect(rows.first()).toContainText('#2');
  await expect(page.getByRole('columnheader', { name: 'Time (local)' })).toHaveAttribute(
    'title',
    'Europe/Zurich',
  );
  expect(
    await page
      .locator('.submission-table-scroll')
      .evaluate((el) => el.scrollWidth <= el.clientWidth),
  ).toBeTruthy();
  await expect(rows.first().locator('time')).toHaveText('2026-09-15 12:00:00');
  await expect(rows.first().getByRole('cell').nth(1)).toContainText('Ada');
  await expect(rows.first().getByRole('cell').nth(2)).toHaveText('Public mathematics');
  await expect(rows.first().getByRole('cell').nth(3)).toHaveText('Statement');
  await expect(rows.first().getByRole('cell').nth(4)).toContainText('Created');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(rows.first()).toContainText('Submission 51');
  await expect(rows.first().getByRole('cell').first()).toHaveText('1150');
  await expect(rows).toHaveCount(50);
  await page.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(rows.first()).toContainText('Submission 1');
  for (let n = 1; n < 10; n++) {
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(rows.first()).toContainText(`Submission ${n * 50 + 1}`);
  }
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
  await expect(rows.last()).toContainText('Submission 500');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await rows.first().evaluate((row) => getComputedStyle(row).whiteSpace)).toBe('nowrap');
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
});
