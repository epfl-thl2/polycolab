import { expect, test, type Page } from '../fixtures';
import type {
  LibraryContent,
  LibraryOwned,
  LibraryPublic,
  LibraryVersion,
} from '../../../../src/web/src/lib/agent-library-api';

test.describe.configure({ timeout: 60_000 });

const entryId = '11111111-1111-4111-8111-111111111111';
const versionId = '22222222-2222-4222-8222-222222222222';
const authorId = '33333333-3333-4333-8333-333333333333';
const data: LibraryContent = {
  title: 'Inspect proof gaps',
  description: 'Check each inference',
  content: 'Review every assumption.',
  instructions: 'Select the statement before starting.',
  tags: ['proof'],
  license: 'CC-BY-4.0',
  runtime: '',
  source_url: '',
  source_reference: '',
};
const version: LibraryVersion = {
  id: versionId,
  entry_id: entryId,
  number: 1,
  content: data,
  author_user_id: authorId,
  author_name: 'Ada',
  published_at: '2026-10-13T10:00:00Z',
};
const entry: LibraryPublic = {
  id: entryId,
  kind: 'PROMPT',
  source_version_id: null,
  source_entry_id: null,
  archived: false,
  version,
};

async function auth(page: Page, signedIn = false) {
  await page.route('**/api/v1/config', (route) =>
    route.fulfill({
      json: {
        agent_execution: false,
        verification_submission: false,
        verification_execution: false,
        email_recovery: false,
      },
    }),
  );
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json:
        new URL(route.request().url()).pathname === '/auth/config'
          ? { mode: 'local', registration_mode: 'open' }
          : { authenticated: signedIn, username: 'ada', display_name: 'Ada' },
    }),
  );
}

test('anonymous library discovery, filters, exact version and copy fallback', async ({ page }) => {
  await auth(page);
  let fail = true;
  await page.route('**/api/v1/agent-library**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/agent-library') {
      if (fail) {
        fail = false;
        return route.fulfill({ status: 503, json: { detail: 'unavailable' } });
      }
      return route.fulfill({
        json: {
          items: url.searchParams.get('kind') === 'PLUGIN' ? [] : [entry],
          next_cursor: null,
        },
      });
    }
    if (url.pathname.endsWith('/versions'))
      return route.fulfill({ json: { items: [version], next_cursor: null } });
    if (url.pathname === `/api/v1/agent-library/${entryId}` || url.pathname.endsWith(versionId))
      return route.fulfill({ json: entry });
    return route.fulfill({ status: 404, json: { detail: 'not_found' } });
  });
  await page.goto('/agents');
  await expect(page.getByRole('heading', { name: 'Agent library', exact: true })).toBeVisible({
    timeout: 20000,
  });
  await expect(
    page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Agents' }),
  ).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('alert')).toContainText('Could not complete');
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await page.getByLabel('Search', { exact: true }).fill('proof');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page).toHaveURL(/q=proof/);
  await page.getByRole('link', { name: 'Inspect proof gaps', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Inspect proof gaps', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('Review every assumption.', { exact: true })).toBeVisible();
  await page.evaluate(() =>
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: () => Promise.reject(new Error('denied')) },
    }),
  );
  await page.getByRole('button', { name: 'Copy prompt', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('copy it manually');
  await expect(page.getByRole('link', { name: 'Sign in to make a copy' })).toHaveAttribute(
    'href',
    /returnTo=/,
  );
  await page.screenshot({
    path: '/private/tmp/polycolab-agent-library-desktop.png',
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole('heading', { name: 'Inspect proof gaps', exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: '/private/tmp/polycolab-agent-library-mobile.png',
    fullPage: true,
  });
  await page.getByRole('link', { name: /^Version 1/ }).click();
  await expect(page).toHaveURL(new RegExp(`/versions/${versionId}$`));
});

test('private editor saves, previews, publishes and retains stale inputs', async ({ page }) => {
  await auth(page, true);
  let owned: LibraryOwned | undefined;
  let publishCount = 0;
  await page.route('**/api/v1/agent-library**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/agent-library' && request.method() === 'POST') {
      expect(request.headers()['idempotency-key']).toBeTruthy();
      const body = request.postDataJSON();
      owned = {
        entry: {
          id: entryId,
          owner_user_id: authorId,
          kind: body.kind,
          revision: 1,
          published_version_id: null,
          source_version_id: null,
          archived: false,
          hidden: false,
          created_at: version.published_at,
        },
        draft: body.content,
        source_entry_id: null,
      };
      return route.fulfill({ status: 201, json: owned });
    }
    if (path.endsWith('/draft') && request.method() === 'GET')
      return route.fulfill({ json: owned });
    if (path.endsWith('/publish')) {
      publishCount += 1;
      expect(request.postDataJSON().expected_revision).toBe(1);
      owned!.entry.revision = 2;
      owned!.entry.published_version_id = versionId;
      return route.fulfill({ json: { ...version, content: owned!.draft } });
    }
    if (path.endsWith('/draft') && request.method() === 'PUT')
      return route.fulfill({ status: 409, json: { detail: 'agent_library_stale_revision' } });
    return route.fulfill({ status: 404, json: { detail: 'not_found' } });
  });
  await page.goto('/agents/new');
  await page.getByLabel('Title', { exact: true }).fill(data.title);
  await page.getByLabel('Description', { exact: true }).fill(data.description);
  await page.getByLabel('Prompt text', { exact: true }).fill(data.content);
  await page.getByLabel('License', { exact: true }).fill(data.license);
  await expect(page.getByRole('button', { name: 'Publish', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/agents/yours/${entryId}/edit$`));
  await page.reload();
  await expect(page.getByLabel('Prompt text', { exact: true })).toHaveValue(data.content);
  await page.getByRole('button', { name: 'Preview publication', exact: true }).click();
  await expect(page.getByRole('heading', { name: data.title, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Publish', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Published version 1');
  expect(publishCount).toBe(1);
  await page.getByRole('button', { name: 'Continue editing', exact: true }).click();
  await page.getByLabel('Prompt text', { exact: true }).fill('Retain this unsaved edit');
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Your inputs are retained');
  await expect(page.getByLabel('Prompt text', { exact: true })).toHaveValue(
    'Retain this unsaved edit',
  );
  const dialog = page.waitForEvent('dialog');
  await page.getByRole('link', { name: 'Back to Yours', exact: true }).click({ noWaitAfter: true });
  await (await dialog).dismiss();
  await expect(page).toHaveURL(new RegExp(`/agents/yours/${entryId}/edit$`));
});

test('skill download and plugin source are explicit external-use actions', async ({ page }) => {
  await auth(page);
  let kind: 'SKILL' | 'PLUGIN' = 'SKILL';
  const skill = '---\nname: proof-review\ndescription: Inspect a proof\n---\nCheck assumptions.';
  await page.route('**/api/v1/agent-library**', (route) => {
    const path = new URL(route.request().url()).pathname;
    const current = {
      ...entry,
      kind,
      version: {
        ...version,
        content: {
          ...data,
          content: kind === 'SKILL' ? skill : '',
          runtime: kind === 'PLUGIN' ? 'Claude Code' : '',
          source_url: kind === 'PLUGIN' ? 'https://example.com/plugin' : '',
        },
      },
    };
    if (path.endsWith('/SKILL.md'))
      return route.fulfill({
        body: skill,
        contentType: 'text/markdown',
        headers: { 'Content-Disposition': 'attachment; filename="SKILL.md"' },
      });
    if (path.endsWith('/versions'))
      return route.fulfill({ json: { items: [current.version], next_cursor: null } });
    return route.fulfill({ json: current });
  });
  await page.goto(`/agents/library/${entryId}`);
  const downloaded = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download SKILL.md', exact: true }).click();
  expect((await downloaded).suggestedFilename()).toBe('SKILL.md');
  kind = 'PLUGIN';
  await page.reload();
  await expect(page.getByRole('link', { name: 'View plugin source', exact: true })).toHaveAttribute(
    'href',
    'https://example.com/plugin',
  );
  await expect(page.getByRole('link', { name: 'View plugin source', exact: true })).toHaveAttribute(
    'rel',
    'noopener noreferrer',
  );
  await expect(page.getByRole('button', { name: /Install/ })).toHaveCount(0);
});

test('long entry metadata fits a mobile screen and sets the resource title', async ({ page }) => {
  await auth(page);
  const title = 'x'.repeat(300);
  const longEntry = {
    ...entry,
    version: {
      ...version,
      content: { ...data, title, description: 'y'.repeat(2000), license: 'z'.repeat(300) },
    },
  };
  await page.route('**/api/v1/agent-library**', (route) =>
    route.fulfill({
      json: new URL(route.request().url()).pathname.endsWith('/versions')
        ? { items: [longEntry.version], next_cursor: null }
        : longEntry,
    }),
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/agents/library/${entryId}`);
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  await expect(page).toHaveTitle(`${title} · Polycolab`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test('a changed draft returned by a save retry cannot publish unreviewed content', async ({
  page,
}) => {
  await auth(page, true);
  const original: LibraryOwned = {
    entry: {
      id: entryId,
      owner_user_id: authorId,
      kind: 'PROMPT',
      revision: 1,
      published_version_id: null,
      source_version_id: null,
      archived: false,
      hidden: false,
      created_at: version.published_at,
    },
    draft: data,
    source_entry_id: null,
  };
  let publications = 0;
  await page.route('**/api/v1/agent-library**', (route) => {
    if (route.request().method() === 'PUT')
      return route.fulfill({
        json: {
          ...original,
          entry: { ...original.entry, revision: 3 },
          draft: { ...data, content: 'Unreviewed private instructions from another edit.' },
        },
      });
    if (route.request().url().endsWith('/publish')) {
      publications += 1;
      return route.fulfill({ json: version });
    }
    return route.fulfill({ json: original });
  });
  await page.goto(`/agents/yours/${entryId}/edit`);
  await page
    .getByLabel('Prompt text', { exact: true })
    .fill('The instructions I actually reviewed.');
  await page.getByRole('button', { name: 'Preview publication', exact: true }).click();
  await page.getByRole('button', { name: 'Publish', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Your inputs are retained');
  await expect(page.getByLabel('Prompt text', { exact: true })).toHaveValue(
    'The instructions I actually reviewed.',
  );
  await expect(page.getByRole('button', { name: 'Publish', exact: true })).toHaveCount(0);
  expect(publications).toBe(0);
});
