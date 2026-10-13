import { expect, test } from '../fixtures';
import { adaId, mockProfiles } from '../helpers/profiles';

test('profile shows one contribution feed and adapts to mobile', async ({ page }, info) => {
  await mockProfiles(page);
  const titles = [
    'A constructive compactness principle',
    'Finite intersection lemma in Lean',
    'Searching for small counterexamples',
    'Notes on finite models',
    'An earlier compactness formulation',
  ];
  const excerpts = [
    'Every finite family of constraints admits a consistent finite model.',
    'Lean source for the finite intersection lemma.',
    'A small-model search for counterexamples to the current statement.',
    'Notes connecting finite models and compactness.',
    'An earlier formulation with stronger assumptions.',
  ];
  await page.route('**/api/v1/profile/ada', (route) =>
    route.fulfill({
      json: {
        actor: { kind: 'human', username: 'ada', display_name: 'Ada' },
        authored_contributions: 5,
        sponsored_contributions: 0,
      },
    }),
  );
  await page.route('**/api/v1/profile/ada/activity*', (route) =>
    route.fulfill({
      json: {
        items: titles.map((title, index) => ({
          id: `00000000-0000-4000-8001-${String(index + 1).padStart(12, '0')}`,
          contribution_id: `00000000-0000-4000-8002-${String(index + 1).padStart(12, '0')}`,
          action: index === 0 ? 'object.revised' : 'object.created',
          actor: { kind: 'human', username: 'ada', display_name: 'Ada' },
          object_id: `00000000-0000-4000-8003-${String(index === 4 ? 1 : index + 1).padStart(12, '0')}`,
          object_version_id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
          object_version_number: 5 - index,
          object_kind: ['STATEMENT', 'FORMALIZATION', 'ATTEMPT', 'NOTE', 'STATEMENT'][index],
          title,
          excerpt_md: excerpts[index],
          project_id: null,
          occurred_at: `2026-10-${String(12 - index).padStart(2, '0')}T10:00:00Z`,
        })),
        next_cursor: null,
      },
    }),
  );
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto('/profile/ada');
  const feed = page.getByRole('region', { name: 'Public contributions', exact: true });
  await expect(feed.getByRole('article')).toHaveCount(5);
  await expect(page.getByRole('link', { name: titles[0], exact: true })).toHaveCount(1);
  await expect(page.getByRole('link', { name: titles[0], exact: true })).toHaveAttribute(
    'href',
    '/commons/records/00000000-0000-4000-8000-000000000001',
  );
  await expect(page.getByRole('region', { name: 'Recent research', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Contribution summary' })).toHaveCount(0);
  const identity = page.getByRole('complementary', { name: 'Profile overview' });
  const calendar = page.getByRole('region', { name: 'Contribution history', exact: true });
  const identityBox = await identity.boundingBox();
  const calendarBox = await calendar.boundingBox();
  expect(identityBox!.x).toBeLessThan(calendarBox!.x);
  await page.screenshot({ path: info.outputPath('profile-overview-desktop.png'), fullPage: true });
  await page.getByRole('combobox', { name: 'Contribution type' }).selectOption('formalizations');
  await expect(feed.getByRole('article')).toHaveCount(1);
  await expect(feed.getByRole('link', { name: titles[1], exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(identity.getByRole('heading', { name: 'Ada', exact: true })).toBeVisible();
  expect((await identity.boundingBox())!.y).toBeLessThan((await calendar.boundingBox())!.y);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath('profile-overview-mobile.png'), fullPage: true });
});

test('personal shortcut resolves the canonical identity and preserves contribution filters', async ({
  page,
}) => {
  await mockProfiles(page, true);
  await page.goto('/profile?type=proofs&year=2026&invalid=1#history');
  await expect(page).toHaveURL(`/profile/ada?type=proofs&year=2026#history`);
  await expect(page.getByRole('heading', { name: 'Ada', exact: true })).toBeVisible();
  await expect(page.getByText('@ada', { exact: true })).toBeVisible();
  await expect(
    page
      .getByRole('region', { name: 'Public contributions', exact: true })
      .getByText("Ada's public proof", { exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByText('@ada', { exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Contribution type' })).toHaveValue('proofs');
});

test('signed-out personal shortcut returns to the canonical profile after sign-in', async ({
  page,
}) => {
  await mockProfiles(page);
  await page.goto('/profile?type=proofs#history');
  await page.getByLabel('Username', { exact: true }).fill('ada');
  await page.getByLabel('Password', { exact: true }).fill('example-password');
  await page.getByRole('main').getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(`/profile/ada?type=proofs#history`);
  await expect(page.getByRole('heading', { name: 'Ada', exact: true })).toBeVisible();
});

test('identity lookup failures can be retried without losing the shortcut filters', async ({
  page,
}) => {
  const state = await mockProfiles(page, true);
  state.identityUnavailable = true;
  await page.goto('/profile?type=proofs');
  await expect(page.getByRole('heading', { name: 'Could not open your profile' })).toBeVisible();
  state.identityUnavailable = false;
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page).toHaveURL(`/profile/ada?type=proofs`);
});

test('an older identity response shows an error instead of waiting forever', async ({ page }) => {
  await mockProfiles(page, true);
  await page.route('**/api/v1/users/me', (route) =>
    route.fulfill({ json: { id: adaId, display_name: 'Ada', email: null } }),
  );
  await page.goto('/profile');
  await expect(page.getByRole('heading', { name: 'Could not open your profile' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
  await expect(page.getByText('Opening your profile…', { exact: true })).toHaveCount(0);
});

test('username profiles work directly while user UUIDs and directory routes stay unavailable', async ({
  page,
}) => {
  await mockProfiles(page);
  await page.goto('/profile/noor');
  await expect(page.getByRole('heading', { name: 'Noor', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('@noor', { exact: true })).toBeVisible();
  await page.goto(`/profile/${adaId}`);
  await expect(page.getByRole('heading', { name: 'Could not load contributions' })).toBeVisible();
  for (const path of ['/profiles', '/profiles/ada', '/people', '/profile/ada/extra']) {
    await page.goto(path);
    await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  }
  await expect(
    page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'People' }),
  ).toHaveCount(0);
});

test('sign-out and account switching clear the cached personal identity', async ({ page }) => {
  await mockProfiles(page, true);
  await page.goto('/profile');
  await expect(page).toHaveURL(`/profile/ada`);
  await page.getByRole('button', { name: 'Open account menu for Ada' }).click();
  await page.getByRole('menuitem', { name: 'Sign out', exact: true }).click();
  await expect(page.getByRole('main').getByText('@ada', { exact: true })).toBeVisible();
  await page.goto('/profile');
  await page.getByLabel('Username', { exact: true }).fill('noor');
  await page.getByLabel('Password', { exact: true }).fill('example-password');
  await page.getByRole('main').getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(`/profile/noor`);
  await expect(page.getByText('@noor', { exact: true })).toBeVisible();
});

test('a delayed identity response cannot redirect a different signed-in account', async ({
  page,
}) => {
  await mockProfiles(page, true);
  let release!: () => void;
  let first = true;
  await page.route('**/api/v1/users/me', async (route) => {
    if (!first) return route.fallback();
    first = false;
    await new Promise<void>((resolve) => {
      release = resolve;
    });
    await route.fulfill({ json: { id: adaId, username: 'ada', display_name: 'Ada', email: null } });
  });
  const pending = page.waitForRequest('**/api/v1/users/me');
  await page.goto('/profile');
  await pending;
  try {
    await page.getByRole('button', { name: 'Open account menu for Ada' }).click();
    await page.getByRole('menuitem', { name: 'Sign out', exact: true }).click();
    await page.getByLabel('Username', { exact: true }).fill('noor');
    await page.getByLabel('Password', { exact: true }).fill('example-password');
    await page.getByRole('main').getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page).toHaveURL(`/profile/noor`);
    const oldResponse = page.waitForResponse(
      (response) => new URL(response.url()).pathname === '/api/v1/users/me',
    );
    release();
    await oldResponse;
    await expect(page.getByText('@noor', { exact: true })).toBeVisible();
    await expect(page).toHaveURL(`/profile/noor`);
  } finally {
    release();
  }
});

test('mobile account navigation opens the personal username profile without a people directory', async ({
  page,
}) => {
  await mockProfiles(page, true);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByRole('button', { name: 'Open navigation and account menu' }).click();
  await expect(page.getByRole('menuitem', { name: 'People', exact: true })).toHaveCount(0);
  await page.getByRole('menuitem', { name: 'Profile', exact: true }).click();
  await expect(page).toHaveURL('/profile/ada');
  await expect(page.getByRole('heading', { name: 'Ada', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
