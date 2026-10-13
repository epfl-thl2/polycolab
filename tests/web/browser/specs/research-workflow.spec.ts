import { expect, test, type Page, type Route } from '../fixtures';

const projectId = '11111111-1111-1111-1111-111111111111';
const objectId = '22222222-2222-2222-2222-222222222222';
const revisionId = '33333333-3333-3333-3333-333333333333';

async function authenticate(page: Page) {
  await page.route('**/auth/config', (route) => route.fulfill({ json: { mode: 'local' } }));
  await page.route('**/auth/me', (route) =>
    route.fulfill({
      json: { authenticated: true, username: 'contributor', display_name: 'Contributor' },
    }),
  );
}

function memberProject(role: 'OWNER' | 'CONTRIBUTOR' | 'READ_ONLY' = 'CONTRIBUTOR') {
  return {
    id: projectId,
    name: 'Prime Patterns',
    description: 'A small project about primes.',
    visibility: 'PUBLIC',
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    current_user_role: role,
  };
}

function revision() {
  return {
    id: revisionId,
    object_id: objectId,
    number: 1,
    kind: 'STATEMENT',
    schema_version: 1,
    content: {
      title: 'Infinitely many primes',
      content_md: '$x^2$ is a square.',
      assumptions_md: 'None stated',
      reported_outcome: null,
      explanation_md: null,
    },
    change_summary: null,
    previous_object_version_id: null,
    structural_relationships: [],
    authorship: {
      actor_kind: 'HUMAN',
      author_user_id: '44444444-4444-4444-4444-444444444444',
      author_display_name: 'Ada',
      agent_id: null,
      agent_display_name: null,
      sponsor_user_id: null,
      contribution_id: null,
    },
    created_at: '2026-01-01T00:00:00Z',
  };
}

function memberObject() {
  const current_object_version = revision();
  return {
    id: objectId,
    project_id: projectId,
    kind: 'STATEMENT',
    current_object_version_id: revisionId,
    current_object_version,
    authorship: current_object_version.authorship,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  };
}

async function mockResearchApi(
  page: Page,
  role: 'OWNER' | 'CONTRIBUTOR' | 'READ_ONLY' = 'CONTRIBUTOR',
) {
  await page.route('**/api/v1/**', async (route: Route) => {
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
    const isPublic = false;
    const object = memberObject();
    if (path === `/api/v1/versions/${revisionId}`) return route.fulfill({ json: revision() });
    if (request.method() === 'POST' && path.endsWith('/versions'))
      return route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          error: { code: 'stale_revision', request_id: '55555555-5555-5555-5555-555555555555' },
        }),
      });
    if (request.method() === 'POST' && path.endsWith('/objects'))
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(object),
      });
    if (isPublic && path.endsWith(`/projects/${projectId}`))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          id: projectId,
          name: 'Prime Patterns',
          description: 'A small project about primes.',
          visibility: 'PUBLIC',
        }),
      });
    if (isPublic && path.endsWith('/objects'))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: objectId,
            kind: 'STATEMENT',
            current_object_version_id: revisionId,
            created_at: object.created_at,
            current_object_version: revision(),
          },
        ]),
      });
    if (isPublic && path.endsWith(`/objects/${objectId}`))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          id: objectId,
          kind: 'STATEMENT',
          current_object_version_id: revisionId,
          created_at: object.created_at,
          current_object_version: revision(),
        }),
      });
    if (isPublic && path.endsWith('/versions'))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ items: [revision()], next_cursor: null }),
      });
    if (isPublic && path.endsWith('/relations'))
      return route.fulfill({ contentType: 'application/json', body: '[]' });
    if (isPublic && path.endsWith('/neighborhood'))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ revision_id: revisionId, relations: [], nodes: [] }),
      });
    if (path.endsWith(`/projects/${projectId}`))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify(memberProject(role)),
      });
    if (path.endsWith('/objects'))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ items: [object], next_cursor: null }),
      });
    if (path.endsWith(`/objects/${objectId}`))
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(object) });
    if (path.endsWith('/versions'))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ items: [revision()], next_cursor: null }),
      });
    if (path.endsWith('/relations'))
      return route.fulfill({ contentType: 'application/json', body: '[]' });
    if (path.endsWith('/neighborhood'))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ revision_id: revisionId, relations: [], nodes: [] }),
      });
    if (path.endsWith('/comments'))
      return route.fulfill({ contentType: 'application/json', body: '[]' });
    return route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'not_found', request_id: '55555555-5555-5555-5555-555555555555' },
      }),
    });
  });
}

test('contributor creates, edits, and receives an actionable stale-revision conflict', async ({
  page,
}) => {
  await authenticate(page);
  await mockResearchApi(page);
  await page.goto(`/projects/${projectId}/research`);
  await expect(
    page.getByRole('complementary', { name: 'Research objects panel' }).getByRole('heading', {
      name: 'Research objects',
      exact: true,
    }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Create object', exact: true }).click();
  await page.getByLabel('Object type').selectOption('PROBLEM');
  await page.getByLabel('Title').fill('A new definition');
  await page.getByRole('textbox', { name: /Content/ }).fill('A fresh definition.');
  await page
    .getByRole('dialog', { name: 'Create object', exact: true })
    .getByRole('button', { name: 'Create object', exact: true })
    .click();

  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  const draft = page.getByLabel('Markdown');
  await draft.fill('My revised proof draft.');
  await page.getByRole('button', { name: 'Save new version' }).click();
  await expect(
    page.getByRole('main').getByRole('alert').filter({ hasText: 'changed while you were editing' }),
  ).toBeVisible();
  await expect(draft).toHaveValue('My revised proof draft.');
  await expect(page.getByRole('button', { name: 'Compare latest version' })).toBeVisible();
});

test('read-only controls are absent', async ({ page }) => {
  await authenticate(page);
  await mockResearchApi(page, 'READ_ONLY');
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await expect(
    page.getByRole('heading', { name: 'Infinitely many primes', level: 1 }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save new version' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Discussion' }).click();
  await expect(page.getByRole('heading', { name: 'Discussion' })).toHaveCount(1);
});

test('version editor sends a complete snapshot and retains its draft on conflict', async ({
  page,
}) => {
  await authenticate(page);
  await mockResearchApi(page);
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  const draft = page.getByLabel('Markdown', { exact: true });
  await draft.fill('My retained proof draft.');
  const write = page.waitForRequest(
    (request) =>
      request.method() === 'POST' &&
      new URL(request.url()).pathname === `/api/v1/objects/${objectId}/versions`,
  );
  await page.getByRole('button', { name: 'Save new version' }).click();
  expect((await write).postDataJSON()).toMatchObject({
    expected_current_object_version_id: revisionId,
    snapshot: {
      kind: 'STATEMENT',
      content: { ...revision().content, content_md: 'My retained proof draft.' },
      structural_relationships: [],
      change_summary: null,
    },
  });
  await expect(page.getByRole('main').getByRole('alert')).toContainText(
    'changed while you were editing',
  );
  await expect(draft).toHaveValue('My retained proof draft.');
  await expect(page.getByRole('heading', { name: 'Latest saved version 1' })).toBeVisible();
  await page.getByRole('button', { name: 'Use latest version as base, keep my draft' }).click();
  await expect(draft).toHaveValue('My retained proof draft.');
  await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
});
