import { test, expect, type Page } from '../fixtures';
import { claimVersion } from '../../unit/version-fixtures';

const entryId = '11111111-1111-4111-8111-111111111111';
const revisionId = '22222222-2222-4222-8222-222222222222';
const projectId = '33333333-3333-4333-8333-333333333333';
const pinId = '44444444-4444-4444-8444-444444444444';
const entry = {
  entry_id: entryId,
  revision_number: 2,
  reported_status: 'Open',
  admitted_at: '2026-09-09T00:00:00Z',
  updated_at: '2026-09-10T00:00:00Z',
  source: {
    identifier: 'Spectral Graph Theory',
    version: '1997',
    locator: 'Chapter 2, Question 4',
  },
  review_rationale:
    'Checked the hypotheses against the cited formulation. The uniform bound remains open.',
  reviewer_display_name: 'Ada',
  reviewed_at: '2026-09-10T00:00:00Z',
  object_version: claimVersion({
    object_id: entryId,
    id: revisionId,
    number: 2,
    kind: 'PROBLEM',
    content: {
      ...claimVersion().content,
      title: 'A uniform spectral gap',
      content_md:
        'For a family of finite regular graphs, is there a constant $c > 0$ such that $\\lambda_2 \\geq c$?',
      assumptions_md: 'Connected, finite, regular graphs with bounded degree.',
    },
  }),
};
const project = {
  id: projectId,
  name: 'Expansion research',
  description: 'Developing bounds for finite graphs.',
  visibility: 'PUBLIC',
  current_user_role: 'OWNER',
  archived_at: null,
  created_at: entry.admitted_at,
  updated_at: entry.updated_at,
};
const pin = {
  id: pinId,
  project_id: projectId,
  object_id: entryId,
  reference_version_id: pinId,
  number: 1,
  previous_reference_version_id: null,
  object_version_id: revisionId,
  latest_object_version_id: revisionId,
  available: true,
  title: entry.object_version.content.title,
  reason: 'Import from Library',
  created_at: entry.updated_at,
};

async function fixture(page: Page, signedIn = true) {
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  await page.route('**/auth/**', (route) => {
    if (new URL(route.request().url()).pathname === '/auth/login') signedIn = true;
    return route.fulfill({
      json:
        new URL(route.request().url()).pathname === '/auth/config'
          ? { mode: 'local', registration_mode: 'open' }
          : { authenticated: signedIn, username: 'ada', display_name: 'Ada' },
    });
  });
  await page.route('**/api/v1/**', (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,

          verification_submission: true,
          verification_execution: false,
          email_recovery: true,
        },
      });
    if (request.method() === 'POST') {
      writes.push({ path, body: request.postDataJSON() });
      if (path === '/api/v1/project-copies')
        return route.fulfill({
          status: 201,
          json: {
            project_id: projectId,
            object_id: pinId,
            object_version_id: pinId,
            source_object_version_id: revisionId,
          },
        });
      if (path === '/api/v1/objects')
        return route.fulfill({
          status: 201,
          json: { outputs: [{ entity_type: 'OBJECT_VERSION', entity_id: 'saved' }] },
        });
      if (path === '/api/v1/catalogue')
        return route.fulfill({
          status: 201,
          json: { entry_id: entryId, object_version_id: revisionId },
        });
    }
    if (path === '/api/v1/library')
      return route.fulfill({ json: { items: [entry], next_cursor: null } });
    if (path.endsWith('/history'))
      return route.fulfill({ json: { items: [entry], next_cursor: null } });
    if (path.startsWith('/api/v1/catalogue/')) return route.fulfill({ json: entry });
    if (path === '/api/v1/projects')
      return route.fulfill({ json: { items: [project], next_cursor: null } });
    if (path === `/api/v1/projects/${projectId}`) return route.fulfill({ json: project });
    if (path === '/api/v1/project-references')
      return route.fulfill({ json: { items: [pin], next_cursor: null } });
    if (path === '/api/v1/discovery')
      return route.fulfill({ json: { items: [], next_cursor: null } });
    return route.fulfill({ json: [] });
  });
  return writes;
}

test('Library discovers a supported statement and copies its exact version into research', async ({
  page,
}) => {
  const writes = await fixture(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/library');
  const result = page.getByRole('table');
  await expect(result.getByText('Open', { exact: true })).toBeVisible();
  await expect(result.getByRole('button')).toHaveCount(0);
  await page.screenshot({ path: '/tmp/polycolab-library-desktop.png', fullPage: true });
  await page.getByRole('link', { name: entry.object_version.content.title, exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Assumptions', exact: true })).toBeVisible();
  await expect(page.locator('.katex').first()).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Status and supporting basis' })).toBeVisible();
  await page.getByRole('button', { name: 'Copy to project' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Destination project').selectOption(projectId);
  await dialog.getByRole('button', { name: 'Create copy' }).click();
  await expect(page).toHaveURL(`/projects/${projectId}/objects/${pinId}`);
  expect(writes[0]).toMatchObject({
    path: '/api/v1/project-copies',
    body: { project_id: projectId, source_object_version_id: revisionId },
  });
});

test('Library is readable on mobile and imports request sign-in in context', async ({ page }) => {
  await fixture(page, false);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/library?kind=PROBLEM&status=Open');
  await expect(
    page.getByRole('link', { name: entry.object_version.content.title, exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/polycolab-library-mobile.png', fullPage: true });
  await page.getByRole('button', { name: 'Filters', exact: true }).click();
  await expect(page.getByRole('combobox', { name: 'Status basis', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/polycolab-library-mobile-filters.png', fullPage: true });
  await page.getByRole('button', { name: 'Filters', exact: true }).click();
  await page.getByRole('link', { name: entry.object_version.content.title, exact: true }).click();
  await page.getByRole('button', { name: 'Copy to project' }).click();
  await expect(page.getByRole('dialog').getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Copy to project' })).toBeFocused();
});

test('Library previews a human-reviewed entry without requiring a literature source', async ({
  page,
}) => {
  const writes = await fixture(page);
  await page.goto('/library');
  await page.getByRole('link', { name: 'Add to Library', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Reviewed question');
  await page.getByLabel('Formulation', { exact: true }).fill('Is every such graph connected?');
  await page.getByLabel('Assumptions', { exact: true }).fill('Finite regular graphs.');
  await page.getByLabel('Recorded status', { exact: true }).selectOption('Open');
  await page.getByRole('checkbox', { name: 'Literature reference' }).uncheck();
  await page
    .getByLabel('My human review (required without literature)', { exact: true })
    .fill('Checked the formulation and unresolved status.');
  await page.getByRole('button', { name: 'Preview entry' }).click();
  await expect(page.getByRole('heading', { name: 'Preview Library entry' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Your review' })).toBeVisible();
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: 'Add to Library', exact: true }).click();
  await expect(page).toHaveURL(`/library/${entryId}`);
  expect(writes[0]).toMatchObject({
    path: '/api/v1/catalogue',
    body: {
      source: null,
      reported_status: 'Open',
      review_rationale: 'Checked the formulation and unresolved status.',
    },
  });
  expect(writes[0]!.body).not.toHaveProperty('reviewed_by_user_id');
});

test('Library sign-in returns to the selected exact version and reopens import', async ({
  page,
}) => {
  await fixture(page, false);
  await page.goto('/library');
  await page.getByRole('link', { name: entry.object_version.content.title, exact: true }).click();
  await page.getByRole('button', { name: 'Copy to project' }).click();
  await page.getByRole('dialog').getByLabel('Username', { exact: true }).fill('ada');
  await page.getByRole('dialog').getByLabel('Password', { exact: true }).fill('test-password-long');
  await page.getByRole('dialog').getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(`/library/${entryId}/revisions/${revisionId}?import=1`);
  await expect(page.getByRole('dialog').getByLabel('Destination project')).toBeVisible();
  await expect(page.getByRole('dialog')).toContainText('Copying version 2');
});

test('Library handles 50 entries across pages, search and mobile layouts', async ({
  page,
}, info) => {
  await fixture(page);
  const titles = [
    'Uniform spectral gaps for bounded-degree graph families',
    'Compactness and finite subcovers',
    'Polynomial-time many-one reductions',
    'An obstruction to extending partial colourings',
    'When does a local-to-global principle hold for compatible finite structures?',
    'Concentration bounds for dependent random variables',
    'A categorical formulation of fixed-point iteration',
    'Completeness of a metric completion',
    'Lower bounds for bounded-depth Boolean circuits',
    'Uniqueness of weak solutions under a coercivity assumption',
  ];
  const entries = Array.from({ length: 50 }, (_, index) => ({
    ...entry,
    entry_id: `entry-${index}`,
    reported_status: ['Open', 'Established', 'Definition', 'Disproved', 'Conjectured'][index % 5],
    updated_at: new Date(Date.UTC(2026, 8, 10 - index)).toISOString(),
    source: index % 3 === 0 ? null : entry.source,
    review_rationale: index % 3 === 1 ? null : entry.review_rationale,
    object_version: {
      ...entry.object_version,
      kind: ['PROBLEM', 'STATEMENT', 'DEFINITION'][index % 3],
      content: {
        ...entry.object_version.content,
        title: `${titles[index % titles.length]} (${index + 1})`,
      },
    },
  }));
  const requests: string[] = [];
  await page.route('**/api/v1/library**', (route) => {
    const url = new URL(route.request().url());
    requests.push(url.search);
    const query = (url.searchParams.get('q') || '').toLowerCase();
    const filtered = entries.filter((item) =>
      item.object_version.content.title.toLowerCase().includes(query),
    );
    const offset = Number(url.searchParams.get('cursor') || 0);
    return route.fulfill({
      json: {
        items: filtered.slice(offset, offset + 25),
        next_cursor: offset + 25 < filtered.length ? String(offset + 25) : null,
      },
    });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/library');
  const rows = page.getByRole('table').locator('tbody').getByRole('row');
  await expect(rows).toHaveCount(25);
  const started = Date.now();
  await page.getByRole('button', { name: 'Load more entries' }).click();
  await expect(rows).toHaveCount(50);
  const appendMs = Date.now() - started;
  await expect(page.getByRole('button', { name: 'Load more entries' })).toHaveCount(0);
  expect(requests[1]).toContain('cursor=25');
  const measure = () =>
    page.evaluate(() => {
      const rows = [...document.querySelectorAll('tbody tr')];
      return {
        width: innerWidth,
        documentHeight: document.documentElement.scrollHeight,
        rowHeights: rows.map((row) => Math.round(row.getBoundingClientRect().height)),
        visibleRows: rows.filter((row) => {
          const box = row.getBoundingClientRect();
          return box.top >= 0 && box.bottom <= innerHeight;
        }).length,
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
      };
    });
  await page.evaluate(() => scrollTo(0, 0));
  const desktop = await measure();
  expect(desktop.horizontalOverflow).toBe(false);
  expect(Math.max(...desktop.rowHeights)).toBeLessThan(90);
  await page.screenshot({ path: '/tmp/polycolab-library-50-desktop.png' });
  await page.screenshot({ path: info.outputPath('50-entries-desktop-full.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  const mobile = await measure();
  expect(mobile.horizontalOverflow).toBe(false);
  await page.screenshot({ path: '/tmp/polycolab-library-50-mobile.png' });
  await rows.last().scrollIntoViewIfNeeded();
  await expect(rows.last().getByRole('link')).toBeVisible();
  await page.getByRole('searchbox', { name: 'Search Library' }).fill('spectral');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(rows).toHaveCount(5);
  expect(requests.at(-1)).toContain('q=spectral');
  expect(requests.at(-1)).not.toContain('cursor=');
  const report = { entries: 50, appendMs, desktop, mobile, filteredCount: await rows.count() };
  console.info('LIBRARY_50_REPORT', JSON.stringify(report));
  await info.attach('layout-measurements', {
    body: JSON.stringify(report, null, 2),
    contentType: 'application/json',
  });
});
