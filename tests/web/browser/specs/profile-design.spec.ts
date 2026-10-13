import { expect, test, type Page } from '../fixtures';

const records = [
  {
    id: 'claim',
    kind: 'STATEMENT',
    title: 'Expansion in sparse graphs',
    content: 'A lower bound for the spectral gap $\\lambda_2$.',
  },
  {
    id: 'proof',
    kind: 'PROOF',
    title: 'A spectral gap bound',
    content:
      'For a connected graph, consider $$\\lambda_2 \\geq c/n^2.$$\n\nThis argument depends on **connectedness**.',
  },
  {
    id: 'sketch',
    kind: 'PROOF',
    title: 'A sketch via the Rayleigh quotient',
    content: 'Reduce the question to an energy estimate.',
  },
  {
    id: 'formal',
    kind: 'FORMALIZATION',
    title: 'A Lean formalization',
    content: 'The finite graph assumptions are stated explicitly.',
  },
  {
    id: 'compute',
    kind: 'NOTE',
    title: 'Numerical spectral experiment',
    content: 'A bounded calculation for $n = 12$.',
  },
  {
    id: 'attempt',
    kind: 'ATTEMPT',
    title: 'An induction attempt',
    content: 'The disconnected case blocks the induction.',
  },
];
function hit(record: (typeof records)[number]) {
  return {
    id: `event-${record.id}`,
    contribution_id: `contribution-${record.id}`,
    object_id: `object-${record.id}`,
    object_version_id: record.id,
    previous_object_version_id: null,
    action: 'object.created',
    object_kind: record.kind,
    title: record.title,
    excerpt_md: record.content,
    actor: { kind: 'human', user_id: 'user-ada', display_name: 'Ada Lovelace' },
    project_id: null,
    occurred_at: '2026-09-10T10:00:00Z',
    reconstructed: false,
  };
}
async function auth(page: Page) {
  await page.route('**/api/v1/me', (route) =>
    route.fulfill({ json: { kind: 'human', user_id: 'user-ada' } }),
  );
  await page.route('**/api/v1/profiles/user-ada', (route) =>
    route.fulfill({
      json: {
        actor: { kind: 'human', user_id: 'user-ada', display_name: 'Ada Lovelace' },
        authored_contributions: 6,
        sponsored_contributions: 0,
      },
    }),
  );
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: true, username: 'ada', display_name: 'Ada Lovelace' },
    }),
  );
}

test('profile puts readable contributions first and preserves search/type in history', async ({
  page,
}, info) => {
  await auth(page);
  await page.route('**/api/v1/profiles/user-ada/activity*', (route) =>
    route.fulfill({
      json: {
        items: [...records.map((record) => hit(record))],
        next_cursor: null,
      },
    }),
  );
  await page.setViewportSize({ width: 1360, height: 1000 });
  await page.goto('/profile');
  await expect(page.getByRole('heading', { name: 'Ada Lovelace', exact: true })).toBeVisible();
  await expect(page.locator('.profile-total strong')).toHaveText('6');
  await expect(page.getByRole('button', { name: 'Proofs', exact: true })).toContainText('2');
  await expect(page.getByRole('link', { name: 'Another researcher' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Private agent attribution' })).toHaveCount(0);
  await expect(page.locator('.profile-feed .katex').first()).toBeVisible();
  await expect(
    page.getByRole('link', { name: 'A spectral gap bound', exact: true }),
  ).toHaveAttribute('href', '/commons/records/proof');
  await expect(page.locator('.profile-feed time').first()).toHaveAttribute('title', /2026/);
  for (const name of ['Your projects', 'Agent connections', 'Manage account']) {
    await expect(page.getByRole('main').getByRole('link', { name, exact: true })).toHaveCount(0);
  }
  await expect(page.getByRole('heading', { name: 'Contribution history' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Contribution year' })).toHaveValue(
    String(new Date().getUTCFullYear()),
  );
  await expect(
    page.getByRole('button', { name: '10 September 2026: 6 loaded contributions' }),
  ).toBeVisible();
  await page.screenshot({ path: info.outputPath('profile-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: 'Proofs', exact: true }).click();
  await expect(page).toHaveURL(/\/profile\?type=proofs$/);
  await expect(page.getByRole('combobox', { name: 'Contribution type' })).toHaveValue('proofs');
  await expect(page.locator('.profile-contribution-card')).toHaveCount(2);
  await page.getByRole('searchbox', { name: 'Search loaded contributions' }).fill('Rayleigh');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page).toHaveURL(/q=Rayleigh&type=proofs$/);
  await expect(page.locator('.profile-contribution-card')).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('searchbox')).toHaveValue('Rayleigh');
  await expect(page.locator('.profile-contribution-card')).toHaveCount(1);
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.locator('.profile-contribution-card')).toHaveCount(6);
  await page.goBack();
  await expect(page.getByRole('searchbox')).toHaveValue('Rayleigh');
  await expect(page.getByRole('combobox', { name: 'Contribution type' })).toHaveValue('proofs');
});

test('mobile profile keeps the feed before summary and covers evidence filters', async ({
  page,
}, info) => {
  await auth(page);
  await page.route('**/api/v1/profiles/user-ada/activity*', (route) =>
    route.fulfill({ json: { items: records.map((record) => hit(record)), next_cursor: null } }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/profile?type=formalizations');
  await expect(page.getByRole('link', { name: 'A Lean formalization', exact: true })).toBeVisible();
  await expect(page.locator('.profile-contribution-card')).toHaveCount(1);
  const feed = await page.locator('.profile-contributions').boundingBox();
  const summary = await page.locator('.profile-summary').boundingBox();
  expect(feed!.y).toBeLessThan(summary!.y);
  await page.getByRole('combobox', { name: 'Contribution type' }).selectOption('research');
  await expect(
    page.getByRole('link', { name: 'Numerical spectral experiment', exact: true }),
  ).toBeVisible();
  await page
    .getByRole('searchbox', { name: 'Search loaded contributions' })
    .fill('No matching research');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'No matching loaded contributions' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Show all contributions' }).click();
  await expect(page.locator('.profile-contribution-card')).toHaveCount(6);
  await expect(page.locator('.profile-planned')).toContainText('Planned');
  await expect(page.getByRole('button', { name: 'Edit profile' })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole('combobox', { name: 'Contribution day' }).selectOption('2026-09-10');
  await expect(page).toHaveURL(/day=2026-09-10$/);
  await expect(page.getByRole('button', { name: 'Show all dates', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: 'Contribution day' }).selectOption('');
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.locator('[aria-label="Contribution day"] option:checked')).toHaveText(
    'All dates',
  );
  await page.getByRole('heading', { name: 'Ada Lovelace', exact: true }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath('profile-mobile.png'), fullPage: true });
  await page
    .locator('.contribution-history')
    .screenshot({ path: info.outputPath('profile-mobile-calendar.png') });
});

test('profile pagination keeps a filtered search and avoids false totals during failure', async ({
  page,
}) => {
  await auth(page);
  let fail = true;
  const cursors: Array<string | null> = [];
  await page.route('**/api/v1/profiles/user-ada/activity*', (route) => {
    const cursor = new URL(route.request().url()).searchParams.get('cursor');
    cursors.push(cursor);
    return route.fulfill(
      cursor
        ? fail
          ? { status: 503, json: { detail: 'Unavailable' } }
          : { json: { items: [hit(records[4])], next_cursor: null } }
        : { json: { items: [hit(records[0])], next_cursor: 'next' } },
    );
  });
  await page.goto('/profile?q=Numerical&type=research');
  await expect(page.getByText(/There may be matches on the next page/)).toBeVisible();
  await page.getByRole('button', { name: 'Load more contributions' }).click();
  await expect(page.getByRole('alert')).toContainText('Could not load contributions');
  await expect(page.locator('.profile-total strong')).toHaveText('1');
  fail = false;
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Numerical spectral experiment' })).toBeVisible();
  await expect(page.locator('.profile-total strong')).toHaveText('2');
  await expect(page.getByRole('combobox', { name: 'Contribution type' })).toHaveValue('research');
  expect(cursors).toEqual([null, 'next', 'next']);
});

test('heatmap filters history by UTC day, survives navigation and incorporates loaded pages', async ({
  page,
}) => {
  await auth(page);
  const first = hit(records[0]);
  first.occurred_at = '2024-02-29T23:30:00-02:00';
  const second = hit(records[1]);
  second.occurred_at = '2024-02-29T12:00:00Z';
  await page.route('**/api/v1/profiles/user-ada/activity*', (route) =>
    route.fulfill({
      json: new URL(route.request().url()).searchParams.has('cursor')
        ? { items: [first, second], next_cursor: null }
        : { items: [first], next_cursor: 'next' },
    }),
  );
  await page.goto('/profile?year=2024');
  const calendar = page.getByRole('region', { name: /Yearly contribution calendar/ });
  await expect(calendar.getByRole('button')).toHaveCount(1);
  const march = calendar.getByRole('button', {
    name: '1 March 2024: 1 loaded contribution',
    exact: true,
  });
  await march.focus();
  await march.press('Enter');
  await expect(page).toHaveURL(/year=2024&day=2024-03-01$/);
  await expect(march).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Load more history', exact: true }).click();
  await expect(calendar.getByRole('button')).toHaveCount(2);
  await expect(page.locator('.profile-total strong')).toHaveText('2');
  await expect(page.locator('.profile-contribution-card')).toHaveCount(1);
  await page
    .getByRole('button', { name: '29 February 2024: 1 loaded contribution', exact: true })
    .click();
  await expect(page.locator('.profile-contribution-card')).toHaveCount(1);
  await expect(page.getByRole('link', { name: 'A spectral gap bound', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.locator('[aria-label="Contribution day"]')).toHaveValue('2024-02-29');
  await expect(
    page.getByRole('heading', { name: 'No matching loaded contributions' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Load more history', exact: true }).click();
  await expect(page.getByRole('link', { name: 'A spectral gap bound', exact: true })).toBeVisible();
  await page.goBack();
  await expect(march).toHaveAttribute('aria-pressed', 'true');
  await page.reload();
  await expect(page.getByRole('combobox', { name: 'Contribution year' })).toHaveValue('2024');
  await expect(march).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Show all dates', exact: true }).click();
  await expect(page).toHaveURL(/year=2024$/);
  await page
    .getByRole('combobox', { name: 'Contribution year' })
    .selectOption(String(new Date().getUTCFullYear()));
  await expect(page.getByText(/0 loaded contributions · 0 active days/)).toBeVisible();
  await expect(calendar.getByRole('button')).toHaveCount(0);
});
