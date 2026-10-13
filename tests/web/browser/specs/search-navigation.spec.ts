import { expect, test } from '../fixtures';
import { claimVersion } from '../../unit/version-fixtures';

test('public search submits URL queries, reloads results and remains available on mobile', async ({
  page,
}) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  await page.route('**/api/v1/discovery?*', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            catalogue_entry_id: 'entry-1',
            object_version: claimVersion({
              id: 'version-1',
              object_id: 'entry-1',
              content: {
                ...claimVersion().content,
                title: 'Spectral theorem',
                content_md: 'A public result.',
              },
            }),
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.route('**/api/v1/projects?*', (route) =>
    route.fulfill({
      json: {
        items: [{ id: 'project-1', name: 'Spectral gaps', description: 'A research project' }],
        next_cursor: null,
      },
    }),
  );
  await page.goto('/');
  await expect(page).toHaveTitle('Home · Polycolab');
  const tools = page.getByRole('navigation', { name: 'Ways to use Polycolab' });
  await expect(tools.getByRole('link', { name: 'Getting started', exact: true })).toHaveAttribute(
    'href',
    '/docs/getting-started/',
  );
  await expect(tools.getByRole('link', { name: 'SKILL.md', exact: true })).toHaveAttribute(
    'href',
    '/SKILL.md',
  );
  await expect(
    tools.getByRole('link', { name: 'Chat with built-in agent Planned' }),
  ).toHaveAttribute('href', '/chat');
  await expect(page.getByRole('heading', { name: 'Explore research', exact: true })).toHaveCount(0);
  await expect(
    page.getByRole('heading', { name: 'Turn a question into collaborative research', exact: true }),
  ).toBeVisible();
  await page.getByRole('searchbox').fill('spectral');
  await page.getByRole('search').getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page).toHaveURL(/\/\?q=spectral$/);
  await expect(page.getByRole('link', { name: 'Spectral theorem' })).toHaveAttribute(
    'href',
    '/library/entry-1',
  );
  await expect(page.getByRole('link', { name: 'Spectral gaps' })).toHaveAttribute(
    'href',
    '/projects/project-1',
  );
  await page.reload();
  await expect(page.getByRole('searchbox')).toHaveValue('spectral');
  await expect(page.getByRole('link', { name: 'Spectral theorem' })).toBeVisible();
  await page.getByRole('button', { name: 'Clear search', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('searchbox')).toHaveValue('');
  await expect(page.getByRole('searchbox')).toBeFocused();
  await expect(page.getByRole('navigation', { name: 'Ways to use Polycolab' })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('searchbox')).toHaveValue('spectral');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('link', { name: 'Polycolab home' })).toHaveAttribute('href', '/');
  await page.getByRole('link', { name: 'Polycolab home' }).click();
  await expect(page).toHaveTitle('Home · Polycolab');
  await expect(page.locator('.product-mobile-context')).toHaveText('Home');
  await expect(
    page.getByRole('heading', { name: 'Turn a question into collaborative research', exact: true }),
  ).toBeVisible();
});
