import { plainFileEditor } from '../helpers/project-editor';
import { test, expect, type Page } from '../fixtures';
import { claimVersion, proofVersion, structuralPin } from '../../unit/version-fixtures';
async function projectInspector(page: Page) {
  if (/\/objects\//.test(new URL(page.url()).pathname))
    await page.getByRole('tab', { name: 'Details', exact: true }).click();
  return page.locator('.project-tools .tool-content');
}
const projectId = '11111111-1111-4111-8111-111111111111';
const objectId = '22222222-2222-4222-8222-222222222222';
const revisionId = '33333333-3333-4333-8333-333333333333';
const sessionId = '44444444-4444-4444-8444-444444444444';
const runId = '55555555-5555-4555-8555-555555555555';
const author = { id: 'author-1', display_name: 'Ada' };
const revision = {
  id: revisionId,
  object_id: objectId,
  number: 1,
  title: 'A spectral gap question',
  content_md: 'Can we bound $\\lambda_2$ uniformly?',
  base_revision_id: null,
  rationale: null,
  author,
  provenance_kind: 'HUMAN_DIRECT',
  created_at: '2026-09-05T12:00:00Z',
};
const object = {
  id: objectId,
  project_id: projectId,
  kind: 'PROBLEM',
  current_object_version_id: revisionId,
  current_object_version: claimVersion({
    id: revisionId,
    object_id: objectId,
    kind: 'PROBLEM',
    number: 1,
    previous_object_version_id: null,
    content: {
      title: revision.title,
      content_md: revision.content_md,
      assumptions_md: 'None stated',
      reported_outcome: null,
      explanation_md: null,
    },
  }),
  authorship: claimVersion().authorship,
  created_at: revision.created_at,
  updated_at: revision.created_at,
};
const project = {
  id: projectId,
  name: 'Spectral gaps',
  description: 'Exploring expansion in finite graphs.',
  visibility: 'PUBLIC',
  current_user_role: 'OWNER',
  member_count: 3,
  archived_at: null,
  created_at: revision.created_at,
  updated_at: revision.created_at,
};

function unsignedJwt(payload: Record<string, unknown>) {
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${encode({ alg: 'none', typ: 'JWT' })}.${encode(payload)}.`;
}

function graphFixture(nodeCount: number, edgeCount: number) {
  const nodes = Array.from({ length: nodeCount }, (_, index) => ({
    object_version_id: `version-${index}`,
    object_id: `object-${index}`,
    title: `Statement ${index}`,
  }));
  const relations = Array.from({ length: edgeCount }, (_, index) => ({
    id: `relation-${index}`,
    source_object_version_id: nodes[index % nodeCount].object_version_id,
    target_object_version_id:
      nodes[(index * 17 + 1 + Math.floor(index / nodeCount)) % nodeCount].object_version_id,
    relationship_type: 'DEPENDS_ON',
    direction: 'UNIDIRECTIONAL',
    binding: 'DECLARATION',
    position: null,
    evidence_role: null,
    description: null,
    ownership_scope_id: null,
    authorship: claimVersion().authorship,
    created_at: revision.created_at,
  }));
  return { object_version_id: nodes[0].object_version_id, nodes, relationships: relations };
}
async function mockProjectGraph(
  page: Page,
  nodeCount: number,
  edgeCount: number,
  kinds: string[] = [],
  progress = false,
) {
  const graph = graphFixture(nodeCount, edgeCount);
  await page.route(`**/api/v1/projects/${projectId}/objects**`, (route) =>
    route.fulfill({
      json: {
        items: graph.nodes.map((node, index) => ({
          ...object,
          id: node.object_id,
          kind: kinds[index] ?? object.kind,
          current_object_version_id: node.object_version_id,
          current_object_version: {
            ...object.current_object_version,
            id: node.object_version_id,
            object_id: node.object_id,
            kind: kinds[index] ?? object.kind,
            content: {
              ...object.current_object_version.content,
              title: node.title,
              ...(progress ? { reported_outcome: 'PARTIAL', reported_progress: 'PARTIAL' } : {}),
            },
          },
        })),
        next_cursor: null,
      },
    }),
  );
  await page.route('**/api/v1/objects/*/relations**', (route) => {
    const id = new URL(route.request().url()).pathname.split('/')[4];
    const revisionId = graph.nodes.find((node) => node.object_id === id)?.object_version_id;
    return route.fulfill({
      json: {
        items: graph.relationships.filter(
          (link) =>
            link.source_object_version_id === revisionId ||
            link.target_object_version_id === revisionId,
        ),
        next_cursor: null,
      },
    });
  });
}
const session = {
  id: sessionId,
  project_id: projectId,
  agent_version_id: 'agent-1',
  agent_kind: 'RESEARCHER',
  agent_version: 1,
  agent_display_name: 'Researcher',
  created_by_user_id: 'author-1',
  title: 'Gap investigation',
  status: 'ACTIVE',
  archived_at: null,
  created_at: revision.created_at,
  updated_at: revision.created_at,
};
async function mock(
  page: Page,
  role = 'OWNER',
  apiLatencyMs = 0,
  agentSessions: Array<typeof session> = [session],
) {
  const requests: string[] = [];
  const apiDelay = () =>
    apiLatencyMs > 0
      ? new Promise<void>((resolve) => setTimeout(resolve, apiLatencyMs))
      : Promise.resolve();
  await page.route('**/auth/**', async (route) => {
    await apiDelay();
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
    await route.fulfill({
      json:
        path === '/auth/config'
          ? { mode: 'local' }
          : { authenticated: true, username: 'ada', display_name: 'Ada' },
    });
  });
  await page.route('**/api/v1/**', async (route) => {
    await apiDelay();
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,

          verification_submission: true,
          verification_execution: false,
          email_recovery: true,
        },
      });
    requests.push(`${request.method()} ${path}`);
    if (path === '/api/v1/agent-capabilities')
      return route.fulfill({
        json: {
          sessions: true,
          execution_available: true,
          hosted_agents: false,
          verification: false,
        },
      });
    if (path === '/api/v1/account/agents')
      return route.fulfill({
        json:
          request.method() === 'POST'
            ? { id: 'agent-1', name: 'Agent', sponsor_user_id: 'author-1' }
            : { items: [], next_cursor: null },
      });
    if (path === '/api/v1/profiles/author-1')
      return route.fulfill({
        json: {
          actor: { kind: 'human', user_id: 'author-1', display_name: 'Ada' },
          authored_contributions: 0,
          sponsored_contributions: 0,
        },
      });
    if (path.endsWith('/activity'))
      return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path === '/api/v1/me')
      return route.fulfill({
        json: {
          kind: 'human',
          user_id: 'author-1',
          agent_key_policy: {
            scope: 'ACCOUNT',
            ttl_seconds: 2592000,
            max_requests: 10000,
            max_mutations: 1000,
          },
        },
      });
    if (
      path === `/api/v1/projects/${projectId}/artifacts` ||
      path === `/api/v1/projects/${projectId}/runs`
    )
      return route.fulfill({ json: { items: [], next_cursor: null } });
    if (path === '/api/v1/discovery')
      return route.fulfill({
        json: {
          items: [
            {
              object_version: object.current_object_version,
              catalogue_entry_id: null,
              catalogue_status: null,
              source_identifier: null,
              source_locator: null,
              source_version: null,
            },
          ],
          next_cursor: null,
        },
      });
    if (path === '/api/v1/account/agent-keys')
      return route.fulfill({
        status: request.method() === 'POST' ? 201 : 200,
        json:
          request.method() === 'POST'
            ? {
                id: 'credential-a',
                project_id: projectId,
                sponsor_user_id: 'author-1',
                name: 'Lean helper',
                secret: 'shown-once-secret',
                created_at: revision.created_at,
                expires_at: '2026-09-10T12:00:00Z',
                revoked_at: null,
                request_count: 0,
                mutation_count: 0,
                max_requests: 100,
                max_mutations: 20,
              }
            : { items: [], next_cursor: null },
      });
    if (path.startsWith('/api/v1/account/agent-keys/'))
      return route.fulfill({ status: 204, body: '' });
    if (path === `/api/v1/projects/${projectId}`)
      return route.fulfill({ json: { ...project, current_user_role: role } });
    if (
      path === `/api/v1/projects/${projectId}/tasks` ||
      path === `/api/v1/projects/${projectId}/worktrees`
    )
      return route.fulfill({ json: [] });
    if (path === '/api/v1/projects')
      return route.fulfill({
        json:
          request.method() === 'POST'
            ? project
            : { items: [{ ...project, current_user_role: role }], next_cursor: null },
      });
    if (path.endsWith(`/objects/${objectId}`)) return route.fulfill({ json: object });
    if (path.endsWith('/objects'))
      return route.fulfill({
        json:
          request.method() === 'POST'
            ? {
                contribution_id: 'contribution-1',
                outputs: [
                  { entity_type: 'RESEARCH_OBJECT', entity_id: objectId },
                  { entity_type: 'OBJECT_VERSION', entity_id: revisionId },
                ],
                replayed: false,
              }
            : { items: [object], next_cursor: null },
      });
    if (path.endsWith('/versions'))
      return route.fulfill({ json: { items: [object.current_object_version], next_cursor: null } });
    if (path.endsWith('/relations') || path.endsWith('/comments'))
      return route.fulfill({ json: { items: [], next_cursor: null } });
    if (
      path.endsWith('/relations') ||
      path.endsWith('/comments') ||
      path.endsWith('/members') ||
      path.endsWith('/invitations') ||
      path.endsWith('/proposals')
    )
      return route.fulfill({ json: [] });
    if (path.endsWith('/neighborhood'))
      return route.fulfill({
        json: {
          object_version_id: revisionId,
          nodes: [{ object_version_id: revisionId, object_id: objectId, title: revision.title }],
          relationships: [],
        },
      });
    if (path.endsWith('/gateway/profiles'))
      return route.fulfill({
        json: [
          {
            id: 'profile-1',
            display_name: 'Research model',
            base_url: 'https://example.com/v1',
            model_id: 'test-model',
            wire_api: 'responses',
          },
        ],
      });
    if (path.endsWith('/platform-agents'))
      return route.fulfill({
        json: [{ id: 'agent-1', agent_kind: 'RESEARCHER', version: 1, display_name: 'Researcher' }],
      });
    if (path === '/api/v1/agent-sessions')
      return route.fulfill({ json: request.method() === 'POST' ? session : agentSessions });
    if (path.endsWith(`/agent-sessions/${sessionId}`)) return route.fulfill({ json: session });
    if (path.endsWith('/messages')) return route.fulfill({ json: [] });
    if (path.endsWith('/events'))
      return route.fulfill({ contentType: 'text/event-stream', body: '' });
    return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } });
  });
  return requests;
}

test('home and primary document do not wait for graphs, histories, or session transcripts', async ({
  page,
}) => {
  const requests = await mock(page);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/projects');
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Spectral gaps', exact: true }).click();
  await page
    .getByRole('navigation', { name: 'Project sections' })
    .getByRole('link', { name: 'Research objects', exact: true })
    .click();
  await expect(
    page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }),
  ).toBeVisible();
  await page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }).click();
  await expect(page.locator('#main').getByRole('heading', { name: revision.title })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Artifacts', exact: true })).toHaveCount(0);
  expect(requests.some((p) => /revisions|relations|messages/.test(p))).toBe(false);
  await expect(page.locator('#main .katex')).toBeVisible();
  expect(errors).toEqual([]);
  await page.screenshot({ path: '/tmp/polycolab-svelte-document.png', fullPage: true });
});

test('public About page gives a concise introduction on desktop and mobile', async ({ page }) => {
  await mock(page);
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
    return route.fulfill({
      json: path === '/auth/config' ? { mode: 'local' } : { authenticated: false },
    });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/about');

  const main = page.getByRole('main');
  await expect(main.getByRole('heading', { level: 1, name: 'About' })).toBeVisible();
  await expect(main.getByRole('article', { name: 'Polycolab' })).toBeVisible();
  await expect(main.getByRole('link')).toHaveCount(0);
  await expect(
    page.getByLabel('Main navigation').getByRole('link', { name: 'Docs', exact: true }),
  ).toBeVisible();
  await expect(page.locator('header').getByRole('link', { name: 'Create account' })).toBeVisible();
  await expect(page.getByLabel('Username')).toHaveCount(0);
  await page.screenshot({ path: '/tmp/polycolab-landing.png', fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(main.getByRole('heading', { name: 'About', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: '/tmp/polycolab-landing-mobile.png', fullPage: true });
});

test('Zensical guides preserve navigation and legacy links on desktop and mobile', async ({
  page,
}, testInfo) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  await page.goto('/docs/');
  await expect(page.getByRole('heading', { name: 'Index', exact: true })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const tabPositions = () =>
    page.locator('.polycolab-docs-tabs .md-tabs__item').evaluateAll((tabs) =>
      tabs.map((tab) => {
        const bounds = tab.getBoundingClientRect();
        return { left: bounds.left, width: bounds.width };
      }),
    );
  const indexTabPositions = await tabPositions();
  await page
    .getByRole('navigation', { name: 'Documentation sections' })
    .getByRole('link', { name: 'Getting started', exact: true })
    .click();
  await expect(page).toHaveURL(/\/docs\/getting-started\/$/);
  await page.evaluate(() => document.fonts.ready);
  expect(await tabPositions()).toEqual(indexTabPositions);
  await page
    .getByRole('navigation', { name: 'Documentation sections' })
    .getByRole('link', { name: 'Index', exact: true })
    .click();
  await expect(page).toHaveURL(/\/docs\/$/);
  const favicon = await page.locator('link[rel~="icon"]').getAttribute('href');
  expect((await page.request.get(favicon!)).status()).toBe(200);
  await page.locator('.md-search__button').click();
  await page.getByRole('combobox').fill('credential');
  await expect(page.locator('div[style*="position: fixed"] a').first()).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: 'Open User Setup →' }).click();
  await expect(page.getByRole('heading', { name: 'User Setup', exact: true })).toBeVisible();
  const docsTabs = page.locator('.polycolab-docs-tabs');
  await expect(docsTabs).toBeVisible();
  const docsToolbar = page.getByRole('navigation', { name: 'Documentation header' });
  await expect(page.getByRole('navigation', { name: 'Documentation sections' })).toBeVisible();
  const toolbarBox = await docsToolbar.boundingBox();
  const tabsBox = await docsTabs.boundingBox();
  expect(tabsBox!.y).toBeGreaterThanOrEqual(toolbarBox!.y + toolbarBox!.height - 1);
  await expect(page.locator('.md-sidebar--primary')).toBeVisible();
  await expect(
    docsTabs.getByRole('link', { name: 'User Setup', exact: true }).locator('..'),
  ).toHaveClass(/md-tabs__item--active/);
  const activeSectionTab = docsTabs.getByRole('link', { name: 'User Setup', exact: true });
  expect((await activeSectionTab.boundingBox())!.height).toBeGreaterThanOrEqual(32);
  expect(
    await activeSectionTab.evaluate((link) => getComputedStyle(link).borderBottomWidth),
  ).not.toBe('0px');
  expect(
    await activeSectionTab
      .locator('..')
      .evaluate((item) => getComputedStyle(item).borderBottomWidth),
  ).toBe('0px');
  const sectionTitle = page.locator(
    '.md-sidebar--primary .md-nav__item--active > .md-nav[data-md-level="1"] > .md-nav__title',
  );
  await expect(sectionTitle).toBeVisible();
  await expect(sectionTitle).toContainText('User Setup');
  expect(await sectionTitle.evaluate((title) => getComputedStyle(title).fontWeight)).toBe('700');
  await expect(sectionTitle.locator('.md-nav__icon')).toBeHidden();
  expect(await sectionTitle.evaluate((title) => getComputedStyle(title).color)).not.toBe(
    await activeSectionTab.evaluate((tab) => getComputedStyle(tab).borderBottomColor),
  );
  await page.getByRole('link', { name: 'Configure your account →' }).click();
  await expect(
    page.getByRole('heading', { name: 'Account and security', exact: true }),
  ).toBeVisible();
  const currentPageLink = page
    .locator('.md-sidebar--primary')
    .getByRole('link', { name: 'Account and security', exact: true });
  await expect(currentPageLink).toHaveClass(/md-nav__link--active/);
  expect(
    await currentPageLink.evaluate((link) => getComputedStyle(link).borderInlineStartWidth),
  ).toBe('2px');
  expect(await currentPageLink.evaluate((link) => getComputedStyle(link).backgroundColor)).toBe(
    'rgba(0, 0, 0, 0)',
  );
  expect(await currentPageLink.evaluate((link) => getComputedStyle(link).whiteSpace)).toBe(
    'normal',
  );
  const pageOutline = page.locator('.md-sidebar--secondary');
  const quietHeadingLink = pageOutline.getByRole('link', { name: 'Create or access your account' });
  expect(await quietHeadingLink.evaluate((link) => getComputedStyle(link).fontWeight)).toBe('400');
  await pageOutline.getByRole('link', { name: 'Review your identity' }).click();
  const currentHeadingLink = pageOutline.locator('a.md-nav__link--active');
  await expect(currentHeadingLink).toBeVisible();
  expect(await currentHeadingLink.evaluate((link) => getComputedStyle(link).backgroundColor)).toBe(
    'rgba(0, 0, 0, 0)',
  );
  expect(await currentHeadingLink.evaluate((link) => getComputedStyle(link).fontWeight)).toBe(
    '600',
  );
  expect(
    await docsTabs
      .getByRole('link', { name: 'API reference', exact: true })
      .evaluate((link: HTMLAnchorElement) => new URL(link.href).pathname),
  ).toBe('/docs/api/');
  await expect(page.getByRole('link', { name: 'Polycolab home' })).toHaveAttribute('href', '/');
  await expect(page.locator('header.product-header')).toHaveCount(0);
  await expect(page.getByRole('navigation', { name: 'Documentation header' })).toBeVisible();
  const referenceLinks = page.getByRole('link', { name: /API reference/ });
  for (const link of await referenceLinks.all()) {
    expect(await link.evaluate((node: HTMLAnchorElement) => new URL(node.href).pathname)).toMatch(
      /^\/docs\/api\/?$/,
    );
  }
  await expect(page.locator('a[href*="/docs/docs/"]')).toHaveCount(0);
  await page.screenshot({ path: '/tmp/polycolab-zensical.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect(docsTabs).toBeHidden();
  await page.locator('label.md-header__button[for="__drawer"]').click();
  await expect(
    page.getByRole('link', { name: 'API reference', exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: '/tmp/polycolab-zensical-mobile.png',
    fullPage: true,
    animations: 'disabled',
  });
  if (!testInfo.project.metadata.productionBuild) {
    await page.goto('/guide');
    await expect(
      page.getByRole('heading', {
        name: 'Getting started',
        exact: true,
      }),
    ).toBeVisible();
    await page.goto('/connect');
    await expect(
      page.getByRole('heading', {
        name: 'Connect an external agent',
        exact: true,
      }),
    ).toBeVisible();
  }
});

test('docs stay focused when an application session is signed in', async ({ page }) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: true, username: 'researcher', display_name: 'Researcher' },
    }),
  );
  await page.goto('/docs/');
  await expect(page.locator('header.product-header')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Projects', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Polycolab home' })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('label.md-header__button[for="__drawer"]').click();
  await expect(
    page
      .locator('.md-sidebar--primary')
      .getByRole('link', { name: 'Developers', exact: true })
      .first(),
  ).toBeVisible();
});

test('footer reaches the viewport bottom on short pages and follows long content', async ({
  page,
}) => {
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json: route.request().url().endsWith('/config')
        ? { mode: 'local' }
        : { authenticated: false },
    }),
  );
  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 390, height: 1000 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('/signin');
    await expect(page.getByRole('textbox', { name: 'Username', exact: true })).toBeVisible();
    const footer = await page.getByRole('contentinfo').boundingBox();
    expect(Math.round(footer!.y + footer!.height)).toBe(viewport.height);
  }
  await page.route('**/api/v1/projects?**', (route) =>
    route.fulfill({
      json: {
        items: Array.from({ length: 20 }, (_, index) => ({
          ...project,
          id: `project-${index}`,
          name: `Research project ${index}`,
        })),
        next_cursor: null,
        total: 20,
      },
    }),
  );
  await page.goto('/projects?scope=public');
  await expect(page.locator('.project-card')).toHaveCount(20);
  const main = await page.locator('main').boundingBox();
  const footer = await page.getByRole('contentinfo').boundingBox();
  expect(footer!.y).toBeGreaterThanOrEqual(main!.y + main!.height);
  expect(footer!.y).toBeGreaterThan(1000);
});

test('account creation reflects the configured local deployment boundary', async ({ page }) => {
  await mock(page);
  let registrationMode: 'open' | 'invitation' | 'closed' = 'closed';
  let externalProviders: Array<'google' | 'github'> = [];
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
    return route.fulfill({
      json:
        path === '/auth/config'
          ? {
              mode: 'local',
              registration_mode: registrationMode,
              social_providers: externalProviders,
            }
          : { authenticated: false },
    });
  });

  await page.goto('/signup');
  await expect(
    page.getByRole('heading', { name: 'Account creation is managed by this deployment' }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: 'Return to sign in' })).toHaveAttribute(
    'href',
    '/signin',
  );

  registrationMode = 'open';
  externalProviders = ['google', 'github'];
  await page.evaluate(() => sessionStorage.removeItem('polycolab.auth-configuration.v1'));
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible();
  await expect(page.getByLabel('Email')).toHaveCount(0);
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await expect(page.getByLabel('Confirm password')).toBeVisible();
  await expect(page.getByLabel('Invitation code')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Continue with Google' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Continue with GitHub' })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/polycolab-open-registration.png', fullPage: true });

  registrationMode = 'invitation';
  await page.evaluate(() => sessionStorage.removeItem('polycolab.auth-configuration.v1'));
  await page.reload();
  await expect(page.getByLabel('Invitation code')).toBeVisible();
});

test('optional recovery setup preserves verified email until its replacement is verified', async ({
  page,
}) => {
  await mock(page);
  let state = {
    verified_email: null as string | null,
    verified_at: null as string | null,
    pending_email: null as string | null,
    pending_requested_at: null as string | null,
  };
  let resendCount = 0;
  await page.route(new RegExp('/api/v1/account/email(?:/resend)?(?:\\?.*)?$'), async (route) => {
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
    if (request.method() === 'GET') return route.fulfill({ json: state });
    if (path.endsWith('/resend')) {
      resendCount += 1;
      return route.fulfill({ json: { accepted: true } });
    }
    const { email } = request.postDataJSON() as { email: string };
    if (email === 'used@example.test')
      return route.fulfill({ status: 409, json: { error: { code: 'recovery_conflict' } } });
    if (email === 'reauth@example.test')
      return route.fulfill({ status: 401, json: { error: { code: 'http_error' } } });
    state = {
      ...state,
      pending_email: email,
      pending_requested_at: revision.created_at,
    };
    return route.fulfill({ json: state });
  });

  await page.goto('/settings/recovery');
  await expect(page.getByText(/Your account is already active/)).toBeVisible();
  await expect(page.getByText('No verified recovery email.')).toBeVisible();
  await page.getByLabel('Recovery email').fill('ada@example.test');
  await page.getByLabel('Current password').fill('test-current-password');
  await page.getByRole('button', { name: 'Verify recovery email' }).click();
  await expect(page.getByRole('status')).toContainText('Check your email');
  await expect(page.getByText(/Pending verification:/)).toContainText('ada@example.test');

  await page.getByRole('button', { name: 'Resend verification' }).click();
  await expect(page.getByRole('status')).toContainText('earlier link no longer works');
  expect(resendCount).toBe(1);

  state = {
    verified_email: 'ada@example.test',
    verified_at: revision.created_at,
    pending_email: null,
    pending_requested_at: null,
  };
  await page.reload();
  await expect(page.getByText(/Verified:/)).toContainText('ada@example.test');
  await page.getByLabel('Recovery email').fill('replacement@example.test');
  await page.getByLabel('Current password').fill('test-current-password');
  await page.getByRole('button', { name: 'Verify recovery email' }).click();
  await expect(page.getByText(/Pending verification:/)).toContainText('replacement@example.test');
  await expect(page.getByText(/current verified address remains available/)).toBeVisible();

  await page.getByLabel('Recovery email').fill('used@example.test');
  await page.getByLabel('Current password').fill('test-current-password');
  await page.getByRole('button', { name: 'Verify recovery email' }).click();
  await expect(page.getByRole('alert')).toContainText('already verified for another account');

  await page.getByLabel('Recovery email').fill('reauth@example.test');
  await page.getByLabel('Current password').fill('test-current-password');
  await page.getByRole('button', { name: 'Verify recovery email' }).click();
  await expect(page.getByRole('alert')).toContainText('Sign in again');
});

test('public recovery remains generic, single-use and clears authenticated state', async ({
  page,
}) => {
  await mock(page);
  const resetRequests: string[] = [];
  let verificationUses = 0;
  let resetUses = 0;
  await page.route('**/api/v1/auth/password-reset/request', async (route) => {
    resetRequests.push((route.request().postDataJSON() as { email: string }).email);
    return route.fulfill({ json: { accepted: true } });
  });
  await page.route('**/api/v1/account/email/verify', (route) => {
    verificationUses += 1;
    return verificationUses === 1
      ? route.fulfill({ json: { accepted: true } })
      : route.fulfill({ status: 400, json: { error: { code: 'invalid_recovery' } } });
  });
  await page.route('**/api/v1/auth/password-reset/confirm', (route) => {
    resetUses += 1;
    return resetUses === 1
      ? route.fulfill({ json: { accepted: true } })
      : route.fulfill({ status: 400, json: { error: { code: 'invalid_recovery' } } });
  });

  for (const address of ['known@example.test', 'unknown@example.test']) {
    await page.goto('/forgot-password');
    await page.getByLabel('Email', { exact: true }).fill(address);
    await page.getByRole('button', { name: 'Send reset link' }).click();
    await expect(page.getByRole('status')).toContainText('If that address belongs');
  }
  expect(resetRequests).toEqual(['known@example.test', 'unknown@example.test']);

  await page.goto('/verify-email?token=verification-secret');
  await page.getByRole('button', { name: 'Verify email' }).click();
  await expect(page.getByRole('status')).toContainText('Email verified');
  await expect(page.locator('a[href*="verification-secret"]')).toHaveCount(0);
  await page.goto('/verify-email?token=verification-secret');
  await page.getByRole('button', { name: 'Verify email' }).click();
  await expect(page.getByRole('alert')).toContainText('invalid, expired, or has already been used');

  await page.goto('/reset-password?token=reset-secret');
  await page.getByLabel('New password', { exact: true }).fill('a secure new password');
  await page.getByLabel('Confirm new password').fill('different password');
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByRole('alert')).toHaveText('Passwords do not match.');
  await page.getByLabel('Confirm new password').fill('a secure new password');
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page).toHaveURL('/signin');
  await expect(page.getByRole('alert')).toContainText('Every existing session was revoked');
  await expect(page.locator('header').getByRole('link', { name: 'Create account' })).toBeVisible();
  await page.goto('/reset-password?token=reset-secret');
  await page.getByLabel('New password', { exact: true }).fill('another secure password');
  await page.getByLabel('Confirm new password').fill('another secure password');
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByRole('alert')).toContainText('invalid, expired, or has already been used');
});

test('warm reload validates one session round trip without flashing signed-out actions', async ({
  page,
}, testInfo) => {
  let configurationRequests = 0;
  let sessionRequests = 0;
  let releaseSession!: () => void;
  let sessionGate = new Promise<void>((resolve) => (releaseSession = resolve));
  await page.route('**/auth/**', async (route) => {
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
    if (path === '/auth/config') {
      configurationRequests += 1;
      return route.fulfill({ json: { mode: 'local' } });
    }
    sessionRequests += 1;
    await sessionGate;
    return route.fulfill({
      json: { authenticated: true, username: 'ada', display_name: 'Ada' },
    });
  });
  await page.route('**/api/v1/discovery**', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );

  await page.goto('/commons');
  await expect(page.getByRole('status', { name: 'Checking account' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Create account' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Sign in to Polycolab' })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/polycolab-auth-loading-header.png' });
  releaseSession();
  await expect(page.getByRole('button', { name: 'Open account menu for Ada' })).toBeVisible();
  expect(configurationRequests).toBe(1);
  expect(sessionRequests).toBe(1);

  sessionGate = new Promise<void>((resolve) => (releaseSession = resolve));
  const reloadStartedAt = performance.now();
  await page.reload();
  await expect(page.getByRole('status', { name: 'Checking account' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Create account' })).toHaveCount(0);
  await expect.poll(() => sessionRequests).toBe(2);
  expect(configurationRequests).toBe(1);
  releaseSession();
  await expect(page.getByRole('button', { name: 'Open account menu for Ada' })).toBeVisible();

  await testInfo.attach('frontend-auth-warm-reload.json', {
    body: JSON.stringify(
      {
        configurationRequests,
        sessionRequests,
        reloadResolutionMs: performance.now() - reloadStartedAt,
        environment: 'Local development server with mocked authentication responses.',
      },
      null,
      2,
    ),
    contentType: 'application/json',
  });
});

test('Explore keeps browsing simple and restores submitted filters from the URL', async ({
  page,
}) => {
  const discoveryQueries: URLSearchParams[] = [];
  await page.setViewportSize({ width: 1440, height: 900 });
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
    return route.fulfill({
      json: path === '/auth/config' ? { mode: 'local' } : { authenticated: false },
    });
  });
  await page.route('**/api/v1/discovery**', (route) => {
    discoveryQueries.push(new URL(route.request().url()).searchParams);
    return route.fulfill({
      json: {
        items: [
          {
            catalogue_entry_id: 'catalogue-1',
            catalogue_status: 'Open',
            source_identifier: 'arXiv:1234.5',
            source_version: 'v2',
            source_locator: 'Theorem 4',
            object_version: proofVersion({
              id: 'version-1',
              object_id: 'object-1',
              content: {
                ...proofVersion().content,
                title: 'A compactness argument',
                content_md: 'Use **finite satisfiability** to construct the required model.',
                reported_outcome: 'PARTIAL',
              },
            }),
          },
        ],
        next_cursor: null,
      },
    });
  });

  await page.goto('/commons?q=compactness&kind=PROOF');
  await expect(page.getByRole('heading', { name: 'Results for “compactness”' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Filters (1)' })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  await expect(page.getByRole('article')).toContainText('Proof');
  await expect(page.getByRole('article')).toContainText('Use finite satisfiability');
  await expect(page.getByRole('button', { name: 'Contribute' })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/polycolab-explore-desktop.png', fullPage: true });

  await page.getByLabel('Author').fill('Ada');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page).toHaveURL(/q=compactness&kind=PROOF&author=Ada/);
  await expect(page.getByRole('button', { name: 'Remove author filter Ada' })).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/q=compactness&kind=PROOF$/);
  await expect(page.getByLabel('Author')).toHaveValue('');
  await expect.poll(() => discoveryQueries.at(-1)?.get('author')).toBeNull();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: 'Filters (1)' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: '/tmp/polycolab-explore-mobile.png', fullPage: true });
});

test('profile presents stable identity and public activity', async ({ page }) => {
  await mock(page);
  await page.route('**/api/v1/profiles/author-1/activity**', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'event-1',
            action: 'object.created',
            actor: { kind: 'human', user_id: 'author-1', display_name: 'Ada' },
            object_id: objectId,
            object_version_id: revisionId,
            object_kind: 'PROOF',
            title: 'A constructive compactness proof',
            project_id: projectId,
            occurred_at: revision.created_at,
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.goto('/profile');
  await expect(page.getByRole('heading', { name: 'Ada', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Public contributions' })).toBeVisible();
  await expect(page.getByText('A constructive compactness proof')).toBeVisible();
  await page.getByRole('button', { name: 'sponsored', exact: true }).click();
  await expect(page.getByRole('button', { name: 'sponsored', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByRole('button', { name: 'Edit profile' })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('retired acceptance routes do not load the legacy project', async ({ page }) => {
  await mock(page);
  await page.goto(`/acceptance/research/${projectId}`);
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Agent chat' })).toHaveCount(0);
});

test('project library recovers from a temporary API outage after an explicit retry', async ({
  page,
}) => {
  await mock(page);
  let unavailable = true;
  await page.route('**/api/v1/projects*', async (route) => {
    if (
      new URL(route.request().url()).pathname === '/api/v1/projects' &&
      route.request().method() === 'GET' &&
      unavailable
    ) {
      unavailable = false;
      return route.fulfill({
        status: 503,
        json: { error: { code: 'temporarily_unavailable' } },
      });
    }
    return route.fallback();
  });

  await page.goto('/projects');
  await expect(page.getByRole('alert')).toContainText('Could not complete the request');
  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Retry' }).click();

  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('an expired API session clears private state and permits local sign-in recovery', async ({
  page,
}) => {
  const requests = await mock(page);
  let expired = true;
  await page.route('**/api/v1/projects*', async (route) => {
    if (
      new URL(route.request().url()).pathname === '/api/v1/projects' &&
      route.request().method() === 'GET' &&
      expired
    ) {
      expired = false;
      return route.fulfill({ status: 401, json: { error: { code: 'unauthenticated' } } });
    }
    return route.fallback();
  });

  await page.goto('/projects?scope=member');
  await expect(
    page.locator('header').getByRole('link', { name: 'Sign in', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toHaveCount(0);
  await page.locator('header').getByRole('link', { name: 'Sign in', exact: true }).click();
  await page.getByLabel('Username').fill('ada');
  await page.getByLabel('Password', { exact: true }).fill('correct-horse-battery-staple');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();

  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  expect(requests.filter((request) => request === 'GET /api/v1/projects')).toHaveLength(1);
});

test('OIDC code flow returns to the exact project and supplies its access token', async ({
  page,
}, testInfo) => {
  await mock(page);
  const origin = new URL(String(testInfo.project.use.baseURL)).origin;
  const issuer = `${origin}/test-oidc`;
  let nonce = '';
  const projectAuthorizations: (string | undefined)[] = [];

  await page.route('**/auth/config', (route) =>
    route.fulfill({
      json: { mode: 'oidc', issuer, client_id: 'polycolab-browser', audience: 'polycolab-api' },
    }),
  );
  await page.route(`${issuer}/.well-known/openid-configuration`, (route) =>
    route.fulfill({
      json: {
        issuer,
        authorization_endpoint: `${issuer}/authorize`,
        token_endpoint: `${issuer}/token`,
        end_session_endpoint: `${issuer}/logout`,
        jwks_uri: `${issuer}/jwks`,
        response_types_supported: ['code'],
        subject_types_supported: ['public'],
        id_token_signing_alg_values_supported: ['none'],
        code_challenge_methods_supported: ['S256'],
      },
    }),
  );
  await page.route(`${issuer}/authorize**`, (route) => {
    const authorization = new URL(route.request().url());
    nonce = authorization.searchParams.get('nonce') ?? '';
    const state = authorization.searchParams.get('state');
    const redirect = authorization.searchParams.get('redirect_uri');
    expect(authorization.searchParams.get('code_challenge_method')).toBe('S256');
    expect(authorization.searchParams.get('audience')).toBe('polycolab-api');
    expect(state).toBeTruthy();
    expect(redirect).toBe(`${origin}/oidc/callback`);
    return route.fulfill({
      status: 302,
      headers: { location: `${redirect}?code=test-code&state=${state}` },
    });
  });
  await page.route(`${issuer}/token`, (route) => {
    const now = Math.floor(Date.now() / 1000);
    return route.fulfill({
      json: {
        access_token: 'oidc-access-token',
        token_type: 'Bearer',
        expires_in: 3600,
        scope: 'openid profile email offline_access',
        id_token: unsignedJwt({
          iss: issuer,
          aud: 'polycolab-browser',
          sub: 'oidc-ada',
          name: 'OIDC Ada',
          nonce,
          iat: now,
          exp: now + 3600,
        }),
      },
    });
  });
  await page.route(`**/api/v1/projects/${projectId}`, async (route) => {
    projectAuthorizations.push(route.request().headers().authorization);
    await route.fallback();
  });

  await page.goto(`/projects/${projectId}`);
  await page.locator('header').getByRole('link', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();

  await expect(page).toHaveURL(`${origin}/projects/${projectId}/sessions/new`);
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Spectral gaps', level: 1 })).toBeVisible();
  expect(projectAuthorizations).toContain('Bearer oidc-access-token');
  await page.goto('/projects');
  await expect(page.getByRole('button', { name: 'Open account menu for OIDC Ada' })).toBeVisible();
});

test('creates a project as public and explains public-on-save behavior', async ({ page }) => {
  await mock(page);
  let createBody: unknown;
  await page.route('**/api/v1/projects', async (route) => {
    if (route.request().method() === 'POST') createBody = route.request().postDataJSON();
    await route.fallback();
  });
  await page.goto('/projects');
  await page.getByRole('button', { name: 'New project' }).click();
  await expect(page.getByText(/Anyone can view this project and its research/)).toBeVisible();
  await page.getByLabel('Project name').fill('Public test project');
  await page.getByLabel('Description').fill('Research anyone can inspect.');
  await page.getByRole('button', { name: 'Create project' }).click();
  await expect(page).toHaveURL(`/projects/${projectId}`);
  expect(createBody).toEqual({
    name: 'Public test project',
    description: 'Research anyone can inspect.',
    visibility: 'PUBLIC',
  });
});

test('anonymous readers browse public projects and exact research after reload', async ({
  page,
}) => {
  await mock(page);
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
    return route.fulfill({
      json: path === '/auth/config' ? { mode: 'local' } : { authenticated: false },
    });
  });

  await page.goto('/projects?scope=public');
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await expect(page.locator('.project-grid .project-card')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'New project' })).toHaveCount(0);
  await page.getByRole('link', { name: 'Spectral gaps' }).click();
  await expect(page.getByRole('navigation', { name: 'Project sections' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Spectral gaps', level: 1 })).toBeVisible();
  await expect(
    page
      .getByRole('navigation', { name: 'Project sections' })
      .getByRole('link', { name: 'Settings' }),
  ).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'State a problem or claim' })).toHaveCount(0);
  await expect(page.getByRole('main')).toContainText('Public');
  await expect(page.getByRole('link', { name: 'Sign in', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Create account' })).toBeVisible();
  await expect(page).toHaveTitle('Spectral gaps · Polycolab');
  await expect(page.locator('#main').getByRole('button')).toHaveCount(0);
  await expect(page.locator('#main').getByRole('link')).toHaveCount(0);
  await page
    .getByRole('navigation', { name: 'Project sections' })
    .getByRole('link', { name: 'Research objects', exact: true })
    .click();
  await page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }).click();
  await expect(page.locator('#main').getByRole('heading', { name: revision.title })).toBeVisible();
  await expect(page).toHaveTitle(`${revision.title} · Polycolab`);
  await expect(page.getByRole('heading', { name: 'Immutable history' })).toBeVisible();
  const navigation = page.getByRole('navigation', { name: 'Project sections' });
  await navigation.getByRole('link', { name: 'Map', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Map', exact: true, level: 1 })).toHaveClass(
    /\bsr-only\b/,
  );
  let recordQuery: URL | undefined;
  await page.route('**/api/v1/discovery?*', (route) => {
    recordQuery = new URL(route.request().url());
    return route.fulfill({ json: { items: [], next_cursor: null } });
  });
  await navigation.getByRole('link', { name: 'Research objects', exact: true }).click();
  await page.getByRole('searchbox', { name: 'Search research objects' }).fill('spectral');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect.poll(() => recordQuery?.searchParams.get('project_id')).toBe(projectId);
  expect(recordQuery?.searchParams.get('q')).toBe('spectral');
  expect(recordQuery?.searchParams.get('scope')).not.toBe('member');
  await expect(page.getByRole('heading', { name: 'No matching research' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Page not found', exact: true })).toHaveCount(0);
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await page.reload();
  await expect(page.locator('#main').getByRole('heading', { name: revision.title })).toBeVisible();
  await expect(
    page.locator('header').getByRole('link', { name: 'Sign in', exact: true }),
  ).toBeVisible();
});

test('public history pagination retains versions and retries the failed page', async ({ page }) => {
  await mock(page, '');
  let fail = true;
  const cursors: Array<string | null> = [];
  const newest = {
    ...object.current_object_version,
    number: 2,
    previous_object_version_id: 'older-version',
  };
  const oldest = {
    ...object.current_object_version,
    id: 'older-version',
    content: { ...object.current_object_version.content, title: 'Earlier saved version' },
  };
  await page.route(`**/api/v1/objects/${objectId}`, (route) =>
    route.fulfill({ json: { ...object, current_object_version: newest } }),
  );
  await page.route(`**/api/v1/objects/${objectId}/versions?*`, (route) => {
    const cursor = new URL(route.request().url()).searchParams.get('cursor');
    cursors.push(cursor);
    return route.fulfill(
      cursor
        ? fail
          ? { status: 503, json: { detail: 'Unavailable' } }
          : {
              json: {
                items: [oldest],
                next_cursor: null,
              },
            }
        : { json: { items: [newest], next_cursor: 'history-2' } },
    );
  });
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await page.getByRole('button', { name: 'Load more history' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByText(`Version 2: ${revision.title}`, { exact: true })).toBeVisible();
  fail = false;
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByText('Version 1: Earlier saved version', { exact: true })).toBeVisible();
  expect(cursors).toEqual([null, 'history-2', 'history-2']);
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('creates, repeatedly reveals, and revokes account-wide agent API keys', async ({ page }) => {
  await mock(page);
  const methods: string[] = [];
  let active = false;
  let failCreate = true;
  const credential = {
    id: 'credential-a',
    secret_reveal_available: true,
    project_id: null,
    scope_kind: 'ACCOUNT',
    sponsor_user_id: 'author-1',
    name: 'Lean helper',
    created_at: revision.created_at,
    expires_at: '2026-09-10T12:00:00Z',
    revoked_at: null,
    request_count: 0,
    mutation_count: 0,
    max_requests: 100,
    max_mutations: 20,
  };
  await page.route(`**/api/v1/account/agent-keys**`, async (route) => {
    const method = route.request().method();
    methods.push(method);
    if (route.request().url().endsWith('/reveal')) {
      return route.fulfill({ json: { secret: 'recoverable-secret' } });
    }
    if (method === 'POST' && failCreate)
      return route.fulfill({ status: 503, json: { error: { code: 'credential_unavailable' } } });
    if (method === 'POST') {
      active = true;
      return route.fulfill({ status: 201, json: { ...credential, secret: 'recoverable-secret' } });
    }
    if (method === 'DELETE') {
      active = false;
      return route.fulfill({ status: 204, body: '' });
    }
    return route.fulfill({ json: { items: active ? [credential] : [], next_cursor: null } });
  });

  await page.goto('/settings/api-keys');
  await expect(page.getByRole('table', { name: 'Your API keys' })).toBeVisible();
  await page.getByRole('button', { name: 'New API key' }).click();
  await page.getByLabel('Polycolab agent name').fill('Lean researcher');
  await page.getByLabel('Key name').fill('Lean helper');
  const keyInputBounds = await page.getByLabel('Key name').boundingBox();
  await page.getByRole('button', { name: 'Create API key' }).click();
  await expect(page.getByRole('alert')).toContainText('secure key service is unavailable');
  expect(await page.getByLabel('Key name').boundingBox()).toEqual(keyInputBounds);
  await expect(page.getByLabel('Key name')).toHaveValue('Lean helper');
  await page.getByRole('button', { name: 'Dismiss notification' }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  failCreate = false;
  await page.getByRole('button', { name: 'Create API key' }).click();
  await expect(page.getByRole('status')).toHaveText('API key created.');
  await expect(page.getByLabel('API key', { exact: true })).toHaveValue('recoverable-secret');
  await page.keyboard.press('Escape');
  await expect(page.getByLabel('API key', { exact: true })).toHaveCount(0);
  await page.reload();
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.getByRole('button', { name: 'Copy API key for Lean helper', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('API key copied.');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('recoverable-secret');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByLabel('API key', { exact: true })).toHaveCount(0);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await page.getByRole('button', { name: 'Actions for Lean helper' }).click();
    await page.getByRole('menuitem', { name: 'Reveal key' }).click();
    await expect(page.getByLabel('API key', { exact: true })).toHaveValue('recoverable-secret');
    await page.getByRole('button', { name: 'Done', exact: true }).click();
    await expect(page.getByLabel('API key', { exact: true })).toHaveCount(0);
  }
  await page.getByRole('button', { name: 'Actions for Lean helper' }).click();
  await page.getByRole('menuitem', { name: 'Revoke key' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(methods).not.toContain('DELETE');
  await expect(page.getByRole('button', { name: 'Actions for Lean helper' })).toBeFocused();
  await page.getByRole('button', { name: 'Actions for Lean helper' }).click();
  await page.getByRole('menuitem', { name: 'Revoke key' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('API key revoked');

  await page.reload();
  await expect(page.getByLabel('API key', { exact: true })).toHaveCount(0);
  expect(methods).toContain('POST');
  expect(methods).toContain('DELETE');
});

test('research objects prioritize search and a readable table', async ({ page }) => {
  await mock(page);
  await mockProjectGraph(page, 3, 0, ['PROBLEM', 'STATEMENT', 'PROOF']);
  await page.goto(`/projects/${projectId}/research`);
  await expect(page.getByRole('heading', { name: 'Research objects', level: 2 })).toBeVisible();
  await expect(page.getByText('3 objects', { exact: true })).toBeVisible();
  const list = page.getByRole('table', { name: 'Research objects' });
  await expect(list.locator('tbody tr')).toHaveCount(3);
  await expect(list.getByRole('columnheader', { name: 'ID', exact: true })).toBeVisible();
  await expect(list.getByRole('button', { name: 'Statement 2' })).toBeVisible();
  await expect(list.locator('[data-object-kind="PROOF"]')).toBeVisible();
  const title = list.getByRole('button', { name: 'Statement 2', exact: true });
  await title.focus();
  await page.keyboard.press('Enter');
  await expect(title).toBeFocused();
  await expect(title).toHaveAttribute('aria-pressed', 'true');
  const panel = await projectInspector(page);
  await expect(panel.getByRole('heading', { name: 'Statement 2', exact: true })).toBeVisible();
  await expect(panel.getByRole('link', { name: 'Open object', exact: true })).toHaveAttribute(
    'href',
    `/projects/${projectId}/objects/object-2`,
  );
  await expect(panel.getByRole('link', { name: 'Open object', exact: true })).not.toHaveAttribute(
    'target',
    '_blank',
  );
  await page.screenshot({ path: '/tmp/polycolab-object-preview.png', fullPage: true });
  const row = title.locator('xpath=ancestor::tr');
  const selectedColor = await row.evaluate((element) => getComputedStyle(element).backgroundColor);
  await row.hover();
  expect(await row.evaluate((element) => getComputedStyle(element).backgroundColor)).toBe(
    selectedColor,
  );
  await list.locator('tbody tr').first().locator('td').last().click();
  await expect(panel.getByRole('heading', { name: 'Statement 0', exact: true })).toBeVisible();

  await expect(page.getByRole('button', { name: /Write a proof sketch/ })).toHaveCount(0);
  await page.getByRole('button', { name: 'Create object', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Create object', exact: true })).toBeVisible();
  await expect(page.getByLabel('Object type')).toHaveValue('PROBLEM');
  await expect(
    page
      .getByRole('dialog', { name: 'Create object', exact: true })
      .getByRole('textbox', { name: 'Title', exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-create-object.png', fullPage: true });
  await page.keyboard.press('Escape');
  await expect(
    page
      .getByRole('complementary', { name: 'Research objects panel' })
      .getByRole('button', { name: 'Create object', exact: true }),
  ).toBeFocused();
  await expect(page.getByRole('button', { name: /Write a proof sketch/ })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Search research' })).toHaveCount(0);
  await page.getByRole('searchbox', { name: 'Search research objects' }).fill('spectral');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Search results' })).toHaveCount(0);
  await expect(page.getByText('1 matching object', { exact: true })).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Clear focus' })).toHaveCount(0);
  await expect(list.getByRole('cell', { name: `Object ID ${objectId}`, exact: true })).toHaveText(
    `${objectId.slice(0, 4)}...`,
  );
  await expect(
    list.getByRole('cell', { name: `Object ID ${objectId}`, exact: true }),
  ).toHaveAttribute('title', objectId);
  await list.getByRole('button', { name: revision.title }).click();
  await expect(panel.getByText('v1', { exact: true })).toBeVisible();
  await expect(panel.getByRole('tab', { name: 'Body', exact: true })).toBeVisible();
  await expect(panel.getByRole('tab', { name: /Relationships/ })).toBeVisible();
  await expect(panel).toContainText('Can we bound');
  await panel.getByRole('tab', { name: /Relationships/ }).click();
  await expect(panel.getByRole('tab', { name: /Relationships/ })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await panel.getByRole('tab', { name: 'Body', exact: true }).click();
  await page.getByRole('button', { name: 'Clear', exact: true }).click();
  await expect(list.locator('tbody tr')).toHaveCount(3);
  await expect(panel.getByRole('button', { name: 'Clear focus' })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/polycolab-research-list.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await title.click();
  const drawer = page.getByRole('dialog', { name: 'Object details', exact: true });
  await expect(drawer.getByRole('heading', { name: 'Statement 2', exact: true })).toBeVisible();
  await drawer.getByRole('button', { name: 'Clear focus' }).click();
  await expect(
    page
      .getByRole('dialog', { name: 'Object details', exact: true })
      .getByText('Select an object to preview its content and version details.'),
  ).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-research-mobile.png', fullPage: true });
  await page.keyboard.press('Escape');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('offers the three primary research writes with exact public version selection', async ({
  page,
}) => {
  await mock(page);
  await page.route('**/api/v1/discovery**', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            object_version: { ...object.current_object_version, kind: 'STATEMENT' },
            catalogue_entry_id: null,
            catalogue_status: null,
            source_identifier: null,
            source_locator: null,
            source_version: null,
          },
        ],
        next_cursor: null,
      },
    }),
  );
  const bodies: Array<Record<string, unknown>> = [];
  await page.route('**/api/v1/objects', async (route) => {
    if (route.request().method() === 'POST') bodies.push(route.request().postDataJSON());
    await route.fallback();
  });

  await page.goto(`/projects/${projectId}/research`);
  await page.getByRole('button', { name: 'Create object', exact: true }).click();
  await page.getByLabel('Object type').selectOption('PROBLEM');
  await page.getByRole('textbox', { name: 'Title', exact: true }).fill('A new problem');
  await page.getByRole('textbox', { name: /Content/ }).fill('Can this bound be improved?');
  await page
    .getByRole('dialog', { name: 'Create object', exact: true })
    .getByRole('button', { name: 'Create object', exact: true })
    .click();

  await page.goto(`/projects/${projectId}/research`);
  await page.getByRole('button', { name: 'Create object', exact: true }).click();
  await page.getByLabel('Object type').selectOption('ATTEMPT');
  await page.getByRole('textbox', { name: 'Title', exact: true }).fill('Inductive attempt');
  await page.getByRole('textbox', { name: /Content/ }).fill('Try induction on graph size.');
  const attemptTarget = page.getByRole('group', { name: /Attempt target/ });
  await attemptTarget.getByRole('searchbox').fill('spectral');
  await attemptTarget.getByRole('button', { name: 'Search' }).click();
  await attemptTarget.getByRole('button', { name: /A spectral gap question/ }).click();
  await page.getByLabel('What was learned').fill('The disconnected case blocks the step.');
  await page
    .getByRole('dialog', { name: 'Create object', exact: true })
    .getByRole('button', { name: 'Create object', exact: true })
    .click();

  await page.goto(`/projects/${projectId}/research`);
  await page.getByRole('button', { name: 'Create object', exact: true }).click();
  await page.getByLabel('Object type').selectOption('PROOF');
  await page.getByRole('textbox', { name: 'Title', exact: true }).fill('Expansion sketch');
  await page
    .getByRole('textbox', { name: /Content/ })
    .fill('Combine the exact premise with expansion.');
  const conclusion = page.getByRole('group', { name: /Conclusion/ });
  await conclusion.getByRole('searchbox').fill('spectral');
  await conclusion.getByRole('button', { name: 'Search' }).click();
  await conclusion.getByRole('button', { name: /A spectral gap question/ }).click();
  await page
    .getByRole('dialog', { name: 'Create object', exact: true })
    .getByRole('button', { name: 'Create object', exact: true })
    .click();

  expect(bodies).toHaveLength(3);
  expect(bodies.map((body) => (body.snapshot as { kind: string }).kind)).toEqual([
    'PROBLEM',
    'ATTEMPT',
    'PROOF',
  ]);
  expect(bodies[1]!.snapshot).toMatchObject({
    structural_relationships: expect.arrayContaining([
      expect.objectContaining({
        relationship_type: 'TARGET',
        target_object_version_id: revisionId,
      }),
    ]),
  });
  expect(bodies[2]!.snapshot).toMatchObject({
    structural_relationships: expect.arrayContaining([
      expect.objectContaining({
        relationship_type: 'CONCLUSION',
        target_object_version_id: revisionId,
      }),
      expect.objectContaining({
        relationship_type: 'ATTACHMENT',
        target_object_version_id: revisionId,
      }),
    ]),
  });
});

test('labels direct external-agent authorship without implying review', async ({ page }) => {
  await mock(page);
  await page.route(`**/api/v1/objects/${objectId}`, (route) =>
    route.fulfill({
      json: {
        ...object,
        current_object_version: {
          ...object.current_object_version,
          authorship: {
            ...object.authorship,
            actor_kind: 'AGENT',
            agent_display_name: 'External researcher',
          },
        },
      },
    }),
  );

  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await expect(page.getByText(/External researcher.*Agent contribution/)).toBeVisible();
  await expect(page.getByText(/Reviewed agent contribution/)).toHaveCount(0);
});

test('skip link moves keyboard focus to primary project content', async ({ page }) => {
  await mock(page);
  await page.goto('/projects');
  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toBeVisible();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

  const skipLink = page.getByRole('link', { name: 'Skip to content' });
  await page.keyboard.press('Tab');
  await expect(skipLink).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('main#main')).toBeFocused();
});

test('project account menu matches the homepage and preserves the current view', async ({
  page,
}) => {
  await mock(page);
  await page.goto('/projects');
  await page.getByRole('button', { name: 'Open account menu for Ada' }).click();
  for (const name of [
    'Profile',
    'Your projects',
    'Settings',
    'Password and authentication',
    'Sign out',
  ])
    await expect(page.getByRole('menuitem', { name, exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: 'Spectral gaps', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Worktrees', exact: true })).toBeVisible();
  const url = page.url();
  await page.getByRole('button', { name: 'Open account menu', exact: true }).click();
  for (const name of [
    'Profile',
    'Your projects',
    'Settings',
    'Password and authentication',
    'Sign out',
  ])
    await expect(page.getByRole('menuitem', { name, exact: true })).toBeVisible();
  await expect(page).toHaveURL(url);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Open account menu', exact: true })).toBeFocused();
  await expect(page.getByRole('menuitem')).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  await page.getByRole('button', { name: 'Open account menu', exact: true }).click();
  await expect(page.getByRole('menuitem', { name: 'Settings', exact: true })).toBeVisible();
  await expect(page).toHaveURL(url);
});

test('avatar menu connects the configured account surfaces', async ({ page }) => {
  await mock(page);
  await page.goto('/projects');

  const trigger = page.getByRole('button', { name: 'Open account menu for Ada' });
  await expect(trigger).toHaveText('A');
  const box = await trigger.boundingBox();
  expect(box?.width).toBe(box?.height);
  await trigger.click();
  await expect(page.getByRole('menuitem', { name: 'API keys' })).toHaveCount(0);
  await expect(page.getByRole('menuitem', { name: 'Administration' })).toHaveCount(0);
  const rows = await page.getByRole('menuitem').evaluateAll((items) =>
    items.map((item) => {
      const { x, y, width, height } = item.getBoundingClientRect();
      return { x, y, width, height };
    }),
  );
  expect(rows).toHaveLength(7);
  for (const [index, row] of rows.entries()) {
    expect(row.height).toBeGreaterThanOrEqual(36);
    expect(row.width).toBeGreaterThan(180);
    expect(row.x).toBe(rows[0].x);
    if (index > 0) expect(row.y).toBeGreaterThanOrEqual(rows[index - 1].y + rows[index - 1].height);
  }
  await page.screenshot({ path: '/tmp/polycolab-account-menu.png' });
  await page.keyboard.press('Escape');

  const destinations = [
    { item: 'Profile', path: '/profile', heading: 'Public contributions' },
    { item: 'Settings', path: '/settings', heading: 'Settings' },
    { item: 'Moderation', path: '/moderation', heading: 'Public research moderation' },
  ];

  await trigger.click();
  await expect(page.getByRole('menuitem', { name: 'Your activities' })).toHaveCount(0);
  await page.keyboard.press('Escape');

  for (const destination of destinations) {
    await trigger.click();
    await page.getByRole('menuitem', { name: destination.item, exact: true }).click();
    await expect(page).toHaveURL(destination.path);
    await expect(
      page.getByRole('heading', { name: destination.heading, exact: true }),
    ).toBeVisible();
    if (destination.item === 'Settings')
      await page.screenshot({ path: '/tmp/polycolab-account-settings.png', fullPage: true });
  }
});

test('production routes expose names for every interactive accessibility node', async ({
  page,
}) => {
  await mock(page);
  const interactiveRoles = new Set([
    'button',
    'checkbox',
    'combobox',
    'link',
    'menuitem',
    'radio',
    'slider',
    'spinbutton',
    'switch',
    'tab',
    'textbox',
  ]);

  const routes = [
    { route: '/projects', heading: 'Projects' },
    { route: `/projects/${projectId}/objects/${objectId}`, heading: revision.title },
    { route: '/settings', heading: 'Settings' },
    { route: '/commons', heading: 'Explore public research' },
    {
      route: '/docs/setup/external-agent/',
      heading: 'Connect an external agent',
    },
    // The legacy /guide redirect is owned by the server, not Vite preview.
    { route: '/docs/getting-started/', heading: 'Getting started' },
  ];
  for (const { route, heading } of routes) {
    await page.goto(route);
    await expect(page.getByRole('heading', { name: heading, exact: true, level: 1 })).toBeVisible();
    const session = await page.context().newCDPSession(page);
    const { nodes } = await session.send('Accessibility.getFullAXTree');
    await session.detach();
    const unnamed = nodes
      .filter(
        (node) =>
          !node.ignored &&
          interactiveRoles.has(String(node.role?.value)) &&
          !String(node.name?.value ?? '').trim(),
      )
      .map((node) => ({ role: node.role?.value, backendDOMNodeId: node.backendDOMNodeId }));
    expect(unnamed, `${route} has unnamed interactive controls`).toEqual([]);
  }
});

test('local account changes clear private project state before signing in again', async ({
  page,
}) => {
  const requests = await mock(page);
  let authenticated = true;
  let username = 'ada';
  await page.route('**/auth/**', async (route) => {
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
    if (path === '/auth/logout') {
      authenticated = false;
      return route.fulfill({ status: 204 });
    }
    if (path === '/auth/login') {
      authenticated = true;
      username = 'grace';
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({
      json:
        path === '/auth/config'
          ? { mode: 'local' }
          : { authenticated, username, display_name: username === 'ada' ? 'Ada' : 'Grace' },
    });
  });

  await page.goto('/projects?scope=member');
  await expect(page.getByRole('button', { name: 'Open account menu for Ada' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Open account menu for Ada' }).click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();

  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toHaveCount(0);
  await page.locator('header').getByRole('link', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible();
  await page.getByLabel('Username').fill('grace');
  await page.getByLabel('Password', { exact: true }).fill('correct-horse-battery-staple');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();

  await expect(page.getByRole('button', { name: 'Open account menu for Grace' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toBeVisible();
  expect(requests.filter((request) => request === 'GET /api/v1/projects')).toHaveLength(2);
});

test('failed local sign-out retains the account and a successful retry clears the error', async ({
  page,
}) => {
  await mock(page);
  let logoutAttempts = 0;
  await page.route('**/auth/logout', async (route) => {
    logoutAttempts += 1;
    if (logoutAttempts === 1)
      return route.fulfill({
        status: 503,
        json: { error: { code: 'temporarily_unavailable' } },
      });
    return route.fulfill({ status: 204 });
  });

  await page.goto('/projects?scope=member');
  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Open account menu for Ada' }).click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();

  await expect(page.getByRole('alert')).toHaveText('Sign-out failed. Please retry.');
  await expect(page.getByRole('button', { name: 'Open account menu for Ada' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Open account menu for Ada' }).click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();

  await expect(
    page.locator('header').getByRole('link', { name: 'Sign in', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toHaveCount(0);
});

test('retains draft on conflict and requires explicit comparison before rebasing', async ({
  page,
}) => {
  await mock(page);
  let saves = 0;
  const newer = claimVersion({
    ...object.current_object_version,
    id: 'newer-version',
    number: 2,
    previous_object_version_id: revisionId,
    content: {
      ...object.current_object_version.content,
      assumptions_md: 'Updated assumptions',
      content_md: 'Concurrent update',
    },
    structural_relationships: [structuralPin('newer-version', 'exact-statement')],
  });
  const saved = {
    ...newer,
    id: 'saved-version',
    number: 3,
    previous_object_version_id: newer.id,
    content: { ...newer.content, content_md: 'My preserved proof draft.' },
  };
  const writes: Record<string, unknown>[] = [];
  await page.route('**/api/v1/versions/*', (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1);
    return route.fulfill({ json: id === revisionId ? object.current_object_version : newer });
  });
  await page.route(`**/api/v1/objects/${objectId}`, (route) =>
    route.fulfill({
      json:
        saves > 1
          ? { ...object, current_object_version_id: saved.id, current_object_version: saved }
          : saves
            ? { ...object, current_object_version_id: newer.id, current_object_version: newer }
            : object,
    }),
  );
  await page.route(`**/api/v1/objects/${objectId}/versions`, async (route) => {
    if (route.request().method() === 'POST') {
      saves++;
      writes.push(route.request().postDataJSON());
      if (saves === 1) return route.fulfill({ status: 409, json: { error: { code: 'conflict' } } });
      return route.fulfill({
        status: 201,
        json: { outputs: [{ entity_type: 'OBJECT_VERSION', entity_id: 'saved-version' }] },
      });
    }
    return route.fallback();
  });
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await page.getByLabel('Markdown', { exact: true }).fill('My preserved proof draft.');
  await page.getByRole('button', { name: 'Save new version' }).click();
  await expect(page.getByRole('alert')).toContainText(
    'saved state, exact dependency set, or authority changed',
  );
  await expect(page.getByLabel('Markdown', { exact: true })).toHaveValue(
    'My preserved proof draft.',
  );
  await expect(
    page.getByRole('button', { name: 'Use latest version as base, keep my draft' }),
  ).toBeVisible();
  expect(saves).toBe(1);
  expect(writes[0]).toMatchObject({ expected_current_object_version_id: revisionId });
  await page.getByRole('button', { name: 'Use latest version as base, keep my draft' }).click();
  await expect(page.getByText('Draft retained. Review and save when ready.')).toBeVisible();
  await page.getByRole('link', { name: 'Research objects', exact: true }).first().click();
  await page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }).click();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(page.getByLabel('Markdown', { exact: true })).toHaveValue(
    'My preserved proof draft.',
  );
  await page.getByRole('button', { name: 'Save new version' }).click();
  await expect.poll(() => saves).toBe(2);
  expect(writes[1]).toMatchObject({
    expected_current_object_version_id: newer.id,
    snapshot: {
      content: { ...newer.content, content_md: 'My preserved proof draft.' },
      structural_relationships: [
        {
          relationship_type: 'ATTACHMENT',
          target_object_version_id: 'exact-statement',
          position: null,
          evidence_role: null,
        },
      ],
    },
  });
  await expect(page.getByRole('status')).toContainText('Version 3 saved.');
});

test('saves exact Python source versions from the production record route with one retry receipt', async ({
  page,
}) => {
  await mock(page);
  const target = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
  const savedId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  const codeRecord = claimVersion({
    id: revisionId,
    object_id: objectId,
    kind: 'NOTE',
    number: 1,
    previous_object_version_id: null,
    content: {
      title: 'Exact Python source',
      source_language: 'PYTHON',
      content_md: 'print("old")',
      assumptions_md: 'CPython 3.13',
      explanation_md: null,
      reported_outcome: 'IN_PROGRESS',
    },
    structural_relationships: [structuralPin(revisionId, target)],
  });
  const writes: Array<{ body: Record<string, unknown>; receipt?: string }> = [];
  await page.route(`**/api/v1/records/${revisionId}*`, (route) =>
    route.fulfill({ json: codeRecord }),
  );
  await page.route(`**/api/v1/versions/${revisionId}`, (route) =>
    route.fulfill({ json: codeRecord }),
  );
  await page.route(`**/api/v1/objects/${objectId}`, (route) =>
    route.fulfill({
      json: {
        ...object,
        kind: codeRecord.kind,
        current_object_version_id: savedId,
        current_object_version: {
          ...codeRecord,
          id: savedId,
          number: 2,
          previous_object_version_id: revisionId,
          content: { ...codeRecord.content, content_md: 'print("new")' },
        },
      },
    }),
  );
  await page.route(`**/api/v1/objects/${objectId}/versions`, (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    writes.push({
      body: route.request().postDataJSON(),
      receipt: route.request().headers()['idempotency-key'],
    });
    if (writes.length === 1)
      return route.fulfill({
        status: 503,
        json: { error: { code: 'temporarily_unavailable' } },
      });
    return route.fulfill({
      status: 201,
      json: {
        contribution_id: 'source-contribution',
        outputs: [{ entity_type: 'OBJECT_VERSION', entity_id: savedId }],
        replayed: false,
      },
    });
  });

  await page.goto(`/projects/${projectId}/records`);
  await page.getByRole('button', { name: 'Add research' }).click();
  await page.getByLabel('Kind').selectOption('FORMALIZATION');
  await expect(page.getByLabel('Saved source')).toBeVisible();
  await page.getByLabel('Kind').selectOption('NOTE');
  await expect(page.getByLabel('Research', { exact: true })).toBeVisible();

  await page.goto(`/projects/${projectId}/records/${revisionId}`);
  await expect(page.getByRole('heading', { name: 'Source editor' })).toBeVisible();
  const sourceEditor = page.locator('section[aria-labelledby^="source-editor-"]');
  await page.getByLabel('Source code').fill('print("new")');
  await page.getByRole('button', { name: 'Save new source version' }).click();
  await expect(sourceEditor.getByRole('alert')).toContainText('draft is retained');
  await page.getByRole('button', { name: 'Save new source version' }).click();
  await expect(page.getByRole('link', { name: 'Open saved version' })).toHaveAttribute(
    'href',
    `/projects/${projectId}/records/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb`,
  );
  expect(writes).toHaveLength(2);
  expect(writes[1].receipt).toBe(writes[0].receipt);
  expect(writes[1].receipt).toBeTruthy();
  expect(writes[1].body).toEqual(writes[0].body);
  expect(writes[1].body).toMatchObject({
    expected_current_object_version_id: revisionId,
    snapshot: {
      kind: 'NOTE',
      content: { ...codeRecord.content, content_md: 'print("new")' },
      structural_relationships: [
        {
          relationship_type: 'ATTACHMENT',
          target_object_version_id: target,
          position: null,
          evidence_role: null,
        },
      ],
      change_summary: 'Update PYTHON source',
    },
  });
});

test('read-only member has no editing, review, or agent requests', async ({ page }) => {
  const requests = await mock(page, 'READ_ONLY');
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await expect(page.locator('#main').getByRole('heading', { name: revision.title })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Edit', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Sessions' })).toHaveCount(0);
  expect(requests.some((p) => p.includes('agent-sessions'))).toBe(false);
});

test('project mode hides project tools and keeps its own navigation', async ({ page }) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/sessions/new`);
  await expect(
    page.getByRole('complementary', { name: 'Project tools', exact: true }),
  ).toBeVisible();
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Spectral gaps', level: 1 })).toBeVisible();
  await expect(page.getByRole('complementary', { name: 'Project tools', exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByRole('tablist', { name: 'Project tabs' })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'Spectral gaps', level: 1 })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('project chat has distinct layout icons and an uncluttered composer', async ({ page }) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/sessions/new`);
  const rail = page.getByRole('complementary', { name: 'Project navigation', exact: true });
  await expect(rail.getByRole('link', { name: 'Project', exact: true }).locator('svg')).toHaveClass(
    /lucide-panels-left-bottom/,
  );
  await expect(rail.getByRole('link', { name: 'Map', exact: true }).locator('svg')).toHaveClass(
    /lucide-map/,
  );
  await expect(page.getByRole('button', { name: 'Choose agent' })).toContainText('Researcher');
  await expect(page.getByLabel('AI provider')).toHaveCount(0);
  const suggested = page.getByLabel('Suggested prompts');
  await expect(suggested.getByRole('button')).toHaveCount(5);
  await suggested.getByRole('button', { name: 'Summarize this project' }).click();
  await expect(page.getByLabel('Message the agent')).toHaveValue('Summarize this project');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: /Customize chat/ }).click();
  await expect(page.getByRole('dialog', { name: 'Customize chat' })).toBeVisible();
  await page.keyboard.press('Escape');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('Main conversations show a collapsible empty state', async ({ page }) => {
  await mock(page, 'OWNER', 0, []);
  await page.goto(`/projects/${projectId}/sessions/new`);
  const panel = page.getByRole('complementary', { name: 'Worktrees', exact: true });
  await expect(panel.getByText('No conversations yet.')).toBeVisible();
  await panel.getByRole('button', { name: 'Toggle Main conversations' }).click();
  await expect(panel.getByText('No conversations yet.')).toHaveCount(0);
});

test('Main groups all loaded conversations without a recent-session cutoff', async ({ page }) => {
  const history = Array.from({ length: 6 }, (_, index) => ({
    ...session,
    id: `session-${index + 1}`,
    title: `Investigation ${index + 1}`,
  }));
  await mock(page, 'OWNER', 0, history);
  await page.goto(`/projects/${projectId}/sessions/new`);
  const group = page.getByRole('region', { name: 'Main worktree' });
  for (let index = 1; index <= 6; index++)
    await expect(
      group.getByRole('button', { name: new RegExp(`Investigation ${index} Researcher`) }),
    ).toBeVisible();
});

test('new chat customizes the hosted prompt and model endpoint', async ({ page }) => {
  await mock(page);
  await page.route('**/api/v1/agent-capabilities', (route) =>
    route.fulfill({
      json: { sessions: true, execution_available: true, hosted_agents: true, verification: false },
    }),
  );
  await page.goto(`/projects/${projectId}/sessions/new`);
  const composer = page.locator('#main .project-chat-start');
  await expect(composer.getByRole('button', { name: 'Choose agent' })).toContainText('Researcher');
  await expect(composer.getByLabel('AI provider')).toHaveCount(0);
  await composer.getByRole('button', { name: /Customize chat/ }).click();
  const customization = page.getByRole('dialog', { name: 'Customize chat' });
  const customToggle = customization.getByRole('button', { name: /Custom instructions/ });
  await customToggle.click();
  await expect(customToggle).toHaveAttribute('aria-pressed', 'true');
  await expect(customization.getByLabel('Harness')).toHaveValue('codex');
  await customization.getByLabel('System prompt').fill('Look for counterexamples first.');
  await page.screenshot({ path: '/tmp/polycolab-custom-chat.png' });
  await page.keyboard.press('Escape');
  await page.getByLabel('Message the agent').fill('Examine this conjecture.');
  const createRequest = page.waitForRequest(
    (request) =>
      request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/agent-sessions',
  );
  await page.getByRole('button', { name: 'Send message' }).click();
  expect((await createRequest).postDataJSON()).toMatchObject({
    agent_kind: 'RESEARCHER',
    harness: 'codex',
    system_prompt: 'Look for counterexamples first.',
  });
  await expect(page).toHaveURL(`/projects/${projectId}/sessions/${sessionId}`);
});

test('new chat top bar stays synchronized and resets local settings', async ({ page }) => {
  await mock(page);
  await page.route('**/api/v1/platform-agents**', (route) =>
    route.fulfill({
      json: [
        { id: 'agent-1', agent_kind: 'RESEARCHER', version: 1, display_name: 'Researcher' },
        { id: 'agent-2', agent_kind: 'CRITIC', version: 1, display_name: 'Critic' },
      ],
    }),
  );
  await page.route('**/api/v1/agent-capabilities', (route) =>
    route.fulfill({
      json: { sessions: true, execution_available: true, hosted_agents: true, verification: false },
    }),
  );
  await page.goto(`/projects/${projectId}/sessions/new`);

  const composer = page.locator('#main .project-chat-start');
  const agentPicker = composer.getByRole('button', { name: 'Choose agent' });
  await expect(agentPicker).toContainText('Researcher');
  await agentPicker.click();
  await page.getByRole('menuitemradio', { name: /Critic/ }).click();
  await expect(agentPicker).toContainText('Critic');
  await agentPicker.click();
  await page.getByRole('menuitemradio', { name: /Researcher/ }).click();
  await expect(composer.getByRole('combobox', { name: 'AI provider' })).toHaveCount(0);
  await composer.getByRole('button', { name: /Customize chat/ }).click();
  const customization = page.getByRole('dialog', { name: 'Customize chat' });
  const context = customization.getByRole('combobox', { name: 'Context scope' });
  await context.selectOption('selected');
  await customization.getByLabel('Response style').selectOption('detailed');
  const customToggle = customization.getByRole('button', { name: /Custom instructions/ });
  await customToggle.click();
  await customization.getByLabel('System prompt').fill('Keep this draft until reset.');
  await customToggle.click();
  await expect(customization.getByLabel('System prompt')).toHaveCount(0);
  await customToggle.click();
  await expect(customization.getByLabel('System prompt')).toHaveValue(
    'Keep this draft until reset.',
  );

  await customization.getByRole('button', { name: 'Reset to defaults' }).click();
  await expect(agentPicker).toContainText('Researcher');
  await expect(customization).toHaveCount(0);
  await composer.getByRole('button', { name: /Customize chat/ }).click();
  await expect(context).toHaveValue('project');
  await expect(customization.getByLabel('Response style')).toHaveValue('balanced');
  await expect(customToggle).toHaveAttribute('aria-pressed', 'false');
  await customToggle.click();
  await expect(customization.getByLabel('System prompt')).toHaveValue('');
});

test('chat composers grow only after overflow and send with Enter', async ({ page }) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/sessions/new`);
  const firstInput = page.getByLabel('Message the agent');
  const initialHeight = (await firstInput.boundingBox())!.height;
  await firstInput.fill('First line\nSecond line');
  await expect.poll(async () => (await firstInput.boundingBox())!.height).toBe(initialHeight);
  const textBox = (await firstInput.boundingBox())!;
  const footerBox = (await page.locator('.project-chat-start-footer').boundingBox())!;
  expect(footerBox.y - (textBox.y + textBox.height)).toBeLessThanOrEqual(1);
  await firstInput.fill('First line\nSecond line\nThird line');
  await expect
    .poll(async () => (await firstInput.boundingBox())!.height)
    .toBeGreaterThan(initialHeight);
  await firstInput.fill(Array.from({ length: 30 }, (_, index) => `Line ${index + 1}`).join('\n'));
  await expect.poll(async () => (await firstInput.boundingBox())!.height).toBe(240);
  await firstInput.fill('First turn');
  await expect.poll(async () => (await firstInput.boundingBox())!.height).toBe(initialHeight);
  await firstInput.press('Shift+Enter');
  await expect(firstInput).toHaveValue('First turn\n');
  await firstInput.press('Enter');
  await expect(page).toHaveURL(`/projects/${projectId}/sessions/${sessionId}`);

  const nextInput = page.getByLabel('Private message', { exact: true });
  if (!(await page.getByLabel('AI provider').isVisible()))
    await page.getByRole('tab', { name: 'Agent history', exact: true }).click();
  await page.getByLabel('AI provider').selectOption('profile-1');
  const nextInitialHeight = (await nextInput.boundingBox())!.height;
  await nextInput.fill('First line\nSecond line');
  await expect.poll(async () => (await nextInput.boundingBox())!.height).toBe(nextInitialHeight);
  await nextInput.fill('First line\nSecond line\nThird line');
  await expect
    .poll(async () => (await nextInput.boundingBox())!.height)
    .toBeGreaterThan(nextInitialHeight);
  await nextInput.fill(Array.from({ length: 30 }, (_, index) => `Line ${index + 1}`).join('\n'));
  await expect.poll(async () => (await nextInput.boundingBox())!.height).toBe(240);
  await nextInput.fill('Follow-up');
  await nextInput.press('Shift+Enter');
  await expect(nextInput).toHaveValue('Follow-up\n');
  const nextTurn = page.waitForRequest(
    (request) => request.method() === 'POST' && request.url().endsWith('/messages'),
  );
  await nextInput.press('Enter');
  expect((await nextTurn).postDataJSON().content_md).toBe('Follow-up');
});

test('new chat keeps its first message and session when the first send fails', async ({ page }) => {
  await mock(page);
  let creations = 0;
  const requestIds: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/agent-sessions')
      creations += 1;
  });
  await page.route('**/api/v1/agent-sessions/*/messages', (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    requestIds.push(route.request().postDataJSON().client_request_id);
    if (requestIds.length === 1)
      return route.fulfill({ status: 503, json: { error: { code: 'temporarily_unavailable' } } });
    return route.fulfill({ json: { message: {}, run: {} } });
  });
  await page.goto(`/projects/${projectId}/sessions/new`);
  const reason = page.locator('.project-chat-start-footer .project-chat-send-reason');
  await expect(reason).toHaveText('Write a message to send.');
  await expect(page.getByText('Choose an AI provider in Customize.')).toHaveCount(0);
  await expect(page.getByLabel('AI provider')).toHaveCount(0);
  await page.getByLabel('Message the agent').fill('Check the smallest counterexample.');
  const send = page.getByRole('button', { name: 'Send message' });
  await expect(reason).toHaveCount(0);
  await expect(send).toBeEnabled();
  await send.click();
  await expect(page.locator('.error-toast').getByRole('alert')).toContainText(
    'temporarily_unavailable',
  );
  await page.getByRole('button', { name: 'Dismiss error' }).click();
  await expect(page.locator('.error-toast')).toHaveCount(0);
  await expect(page.getByLabel('Message the agent')).toHaveValue(
    'Check the smallest counterexample.',
  );
  await send.click();
  await expect(page).toHaveURL(`/projects/${projectId}/sessions/${sessionId}`);
  expect(creations).toBe(1);
  expect(requestIds).toHaveLength(2);
  expect(requestIds[0]).toBe(requestIds[1]);
});

test('failed agent message remains editable and successful retry uses the same receipt', async ({
  page,
}) => {
  await mock(page);
  const bodies: Record<string, unknown>[] = [];
  await page.route('**/api/v1/agent-sessions/*/messages', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    const body = route.request().postDataJSON();
    bodies.push(body);
    if (bodies.length === 1)
      return route.fulfill({ status: 503, json: { error: { code: 'temporarily_unavailable' } } });
    return route.fulfill({
      json: {
        message: {
          id: 'message-1',
          session_id: sessionId,
          role: 'USER',
          content_md: body.content_md,
          sequence: 1,
        },
        run: { id: runId, status: 'QUEUED' },
      },
    });
  });
  await page.goto(`/projects/${projectId}/sessions/${sessionId}`);
  if (!(await page.getByLabel('AI provider').isVisible()))
    await page.getByRole('tab', { name: 'Agent history', exact: true }).click();
  await expect(page.getByLabel('AI provider')).toBeVisible();
  await expect(page.locator('.project-chat-composer .project-chat-send-reason')).toHaveText(
    'Choose an AI provider in Chat settings.',
  );
  await page.screenshot({ path: '/tmp/polycolab-enabled-chat-after.png' });
  if (!(await page.getByLabel('AI provider').isVisible()))
    await page.getByRole('tab', { name: 'Agent history', exact: true }).click();
  await page.getByLabel('AI provider').selectOption('profile-1');
  await page.getByText('Run settings', { exact: true }).click();
  await page.getByText('Context · 0 pinned versions').click();
  await page.getByRole('checkbox').check();
  await page.getByText('Artifact context · 0 exact IDs').click();
  await page
    .getByLabel('Exact committed artifact IDs (comma or whitespace separated)')
    .fill('artifact-exact-1, artifact-exact-1');
  await page.getByLabel('Private message', { exact: true }).fill('Explore the gap.');
  await expect(page.locator('.project-chat-composer .project-chat-send-reason')).toHaveCount(0);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.locator('.error-toast').getByRole('alert')).toContainText(
    'temporarily_unavailable',
  );
  await expect(page.getByLabel('Private message', { exact: true })).toHaveValue('Explore the gap.');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByLabel('Private message', { exact: true })).toHaveValue('');
  await expect(page.locator('.error-toast')).toHaveCount(0);
  expect(bodies[1].client_request_id).toBe(bodies[0].client_request_id);
  expect(bodies[1].context_object_version_ids).toEqual([revisionId]);
  expect(bodies[1].context_artifact_ids).toEqual(['artifact-exact-1']);
});

test('mobile document remains readable without horizontal page overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page);
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await expect(page.locator('#main').getByRole('heading', { name: revision.title })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: '/tmp/polycolab-svelte-mobile.png', fullPage: true });
});

test('hostile Markdown stays inert and readable on a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page);
  const hostileContent = [
    '# Safe heading',
    '<script>window.__polycolabInjected = true</script>',
    '[unsafe link](javascript:window.__polycolabInjected=true)',
    `Long source token: ${'x'.repeat(1_000)}`,
  ].join('\n\n');
  await page.route(`**/api/v1/objects/${objectId}`, (route) =>
    route.fulfill({
      json: {
        ...object,
        current_object_version: {
          ...object.current_object_version,
          content: { ...object.current_object_version.content, content_md: hostileContent },
        },
      },
    }),
  );
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await expect(page.getByRole('heading', { name: 'Safe heading' })).toBeVisible();
  await expect(page.locator('.prose script')).toHaveCount(0);
  await expect(page.locator('.prose a[href^="javascript:"]')).toHaveCount(0);
  expect(await page.evaluate(() => Reflect.get(window, '__polycolabInjected'))).toBeUndefined();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
});

test('streams committed agent events, reconnects from cursor and cancels the run', async ({
  page,
}) => {
  await mock(page);
  let connections = 0;
  const cursors: (string | undefined)[] = [];
  let cancelled = false;
  await page.route('**/api/v1/agent-sessions/*/runs*', (route) =>
    route.fulfill({ json: [{ id: runId, status: cancelled ? 'CANCELLED' : 'RUNNING' }] }),
  );
  await page.route('**/api/v1/agent-runs/*', (route) =>
    route.fulfill({ json: { id: runId, status: 'RUNNING' } }),
  );
  await page.route('**/api/v1/agent-runs/*/cancel', (route) => {
    cancelled = true;
    return route.fulfill({ json: { id: runId, status: 'CANCELLED' } });
  });
  await page.route('**/api/v1/agent-sessions/*/events', (route) => {
    cursors.push(route.request().headers()['last-event-id']);
    connections++;
    const event = {
      run_id: runId,
      cursor: 1,
      kind: 'RUN_STARTED',
      payload: {},
      occurred_at: revision.created_at,
    };
    const delta = {
      ...event,
      cursor: 2,
      kind: 'ASSISTANT_DELTA',
      payload: { text: 'A useful next step.' },
    };
    return route.fulfill({
      contentType: 'text/event-stream',
      body:
        connections === 1
          ? `id: 1:1\nevent: RUN_STARTED\ndata: ${JSON.stringify(event)}\n\nid: 1:2\nevent: ASSISTANT_DELTA\ndata: ${JSON.stringify(delta)}\n\n`
          : `id: 1:2\nevent: ASSISTANT_DELTA\ndata: ${JSON.stringify(delta)}\n\n`,
    });
  });
  await page.goto(`/projects/${projectId}/sessions/${sessionId}`);
  await expect(page.getByText('A useful next step.', { exact: true })).toBeVisible();
  await expect.poll(() => connections).toBeGreaterThan(1);
  expect(cursors[1]).toBe('1:2');
  await expect(page.getByText('A useful next step.', { exact: true })).toHaveCount(1);
  await page.getByRole('button', { name: 'Cancel run' }).click();
  expect(cancelled).toBe(true);
  await expect(page.getByRole('button', { name: 'Resume run' })).toBeVisible();
});

test('revoked session access clears private messages and stops event reconnects', async ({
  page,
}) => {
  await mock(page);
  let eventRequests = 0;
  await page.route('**/api/v1/agent-sessions/*/messages', (route) =>
    route.fulfill({
      json: [
        {
          id: 'private-message-1',
          session_id: sessionId,
          role: 'USER',
          content_md: 'Private draft that must be cleared after revocation.',
          created_at: revision.created_at,
        },
      ],
    }),
  );
  await page.route('**/api/v1/agent-sessions/*/events', (route) => {
    eventRequests += 1;
    return route.fulfill({
      status: 403,
      json: { error: { code: 'forbidden' } },
    });
  });

  await page.goto(`/projects/${projectId}/sessions/${sessionId}`);
  await expect(page.getByRole('alert')).toContainText('access changed');
  await expect(page.getByText('Private draft that must be cleared after revocation.')).toHaveCount(
    0,
  );
  expect(eventRequests).toBe(1);
  await page.waitForTimeout(1_100);
  expect(eventRequests).toBe(1);
});

test('moderation retains exact inputs and retry identity while authority recovers', async ({
  page,
}) => {
  await mock(page);
  let authorized = false;
  const attempts: Array<{ body: unknown; key?: string }> = [];
  await page.route(`**/api/v1/records/objects/${objectId}/moderation`, (route) => {
    attempts.push({
      body: route.request().postDataJSON(),
      key: route.request().headers()['idempotency-key'],
    });
    return authorized
      ? route.fulfill({ status: 204 })
      : route.fulfill({ status: 403, json: { error: { code: 'forbidden' } } });
  });

  await page.goto('/moderation');
  await page.getByLabel('Object or catalogue entry ID').fill(objectId);
  await page.getByLabel('Exact current version ID').fill(revisionId);
  await page.getByLabel('Reason').fill('Contains private material pending a safe revision.');
  await page.getByRole('button', { name: 'Apply moderation' }).click();

  await expect(page.getByRole('alert')).toContainText('access changed');
  await expect(page.getByLabel('Object or catalogue entry ID')).toHaveValue(objectId);
  await expect(page.getByLabel('Exact current version ID')).toHaveValue(revisionId);
  await expect(page.getByLabel('Reason')).toHaveValue(
    'Contains private material pending a safe revision.',
  );

  authorized = true;
  await page.getByRole('button', { name: 'Apply moderation' }).click();
  await expect(page.getByRole('status')).toHaveText('Hidden with an immutable moderation reason.');
  expect(attempts).toHaveLength(2);
  expect(attempts[0].key).toBeTruthy();
  expect(attempts[1].key).toBe(attempts[0].key);
  expect(attempts[1].body).toEqual(attempts[0].body);
});

test('inspects, replays and cancels an exact verification job while execution stays gated', async ({
  page,
}) => {
  await mock(page);
  const jobId = '66666666-6666-4666-8666-666666666666';
  const sourceRevisionId = '77777777-7777-4777-8777-777777777777';
  let cancelled = false;
  const verificationRequests: string[] = [];
  const job = () => ({
    id: jobId,
    manifest_digest: 'a'.repeat(64),
    state: cancelled ? 'CANCELLED' : 'RUNNING',
    generation: 1,
    event_sequence: cancelled ? 3 : 2,
    deadline_at: '2026-09-08T02:00:00Z',
    terminal_reason: cancelled ? 'USER_CANCELLED' : null,
    submission: {
      version: 1,
      project_id: projectId,
      work_target_object_version_id: revisionId,
      research_attempt_object_version_id: null,
      environment_id: '88888888-8888-4888-8888-888888888888',
      purpose: 'PYTHON_RUN',
      evidence_scope: 'Measures this exact computation only.',
      inputs: [{ path: 'main.py', role: 'SOURCE', object_version_id: sourceRevisionId }],
      entrypoint: 'main.py',
      arguments: [],
      seed: 7,
      limits: {
        cpu_count: 1,
        cpu_seconds: 30,
        wall_seconds: 60,
        memory_bytes: 268435456,
        process_count: 8,
        disk_bytes: 268435456,
        output_bytes: 1048576,
        log_bytes: 1048576,
        output_files: 8,
      },
    },
    attempts: [],
    results: [],
  });
  await page.route('**/api/v1/projects/*/verification-jobs/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    verificationRequests.push(`${request.method()} ${url.pathname}`);
    if (url.pathname.endsWith('/events')) {
      const after = Number(url.searchParams.get('after_sequence') ?? 0);
      const events = [
        {
          sequence: 1,
          attempt_id: null,
          event_type: 'ADMITTED',
          created_at: '2026-09-08T01:00:00Z',
        },
        {
          sequence: 2,
          attempt_id: '99999999-9999-4999-8999-999999999999',
          event_type: 'CLAIMED',
          created_at: '2026-09-08T01:00:01Z',
        },
        ...(cancelled
          ? [
              {
                sequence: 3,
                attempt_id: '99999999-9999-4999-8999-999999999999',
                event_type: 'CANCELLED',
                created_at: '2026-09-08T01:00:02Z',
              },
            ]
          : []),
      ];
      return route.fulfill({ json: events.filter((event) => event.sequence > after) });
    }
    if (url.pathname.endsWith('/cancel')) {
      cancelled = true;
      return route.fulfill({ json: job() });
    }
    return route.fulfill({ json: job() });
  });
  await page.route('**/api/v1/research/versions/display', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            object_version_id: revisionId,
            object_id: objectId,
            kind: 'STATEMENT',
            title: revision.title,
          },
          {
            object_version_id: sourceRevisionId,
            object_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
            kind: 'NOTE',
            title: 'Exact Python source',
          },
        ],
      },
    }),
  );

  await page.goto(`/projects/${projectId}/verification/${jobId}`);
  await expect(page.getByRole('heading', { name: jobId })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Exact Python source' })).toBeVisible();
  await expect(page.getByText(/#2 CLAIMED/)).toBeVisible();
  await page.getByRole('button', { name: 'Cancel job' }).click();

  await expect(page.getByText('CANCELLED', { exact: true })).toBeVisible();
  await expect(page.getByText(/#3 CANCELLED/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Rerun exact job' })).toBeDisabled();
  await expect(page.getByText(/Linux isolation gate/)).toBeVisible();
  expect(verificationRequests).toContain(
    `POST /api/v1/projects/${projectId}/verification-jobs/${jobId}/cancel`,
  );
});

test('discovers a curated environment and retains an exact verification submission for retry', async ({
  page,
}) => {
  await mock(page);
  const environmentId = '77777777-7777-4777-8777-777777777777';
  const sourceRevisionId = '88888888-8888-4888-8888-888888888888';
  const submittedJobId = '99999999-9999-4999-8999-999999999999';
  const limits = {
    cpu_count: 2,
    cpu_seconds: 60,
    wall_seconds: 120,
    memory_bytes: 536_870_912,
    process_count: 16,
    disk_bytes: 536_870_912,
    output_bytes: 2_097_152,
    log_bytes: 1_048_576,
    output_files: 8,
  };
  await page.route(`**/api/v1/projects/${projectId}/verification-environments*`, (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: environmentId,
            language: 'PYTHON',
            image_digest: 'a'.repeat(64),
            toolchain_version: 'CPython 3.13.7',
            dependency_lock_digest: 'b'.repeat(64),
            build_digest: 'c'.repeat(64),
            platform_identity: 'linux/arm64/gvisor',
            limits,
            created_at: revision.created_at,
            availability_changed_at: revision.created_at,
          },
        ],
        next_after: null,
      },
    }),
  );
  const submissions: Record<string, unknown>[] = [];
  await page.route(`**/api/v1/projects/${projectId}/verification-jobs`, (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    submissions.push(route.request().postDataJSON());
    if (submissions.length === 1)
      return route.fulfill({
        status: 503,
        json: { error: { code: 'temporarily_unavailable' } },
      });
    return route.fulfill({ status: 201, json: { id: submittedJobId } });
  });

  await page.goto(`/projects/${projectId}/verification`);
  await page.getByLabel('Exact curated environment').selectOption(environmentId);
  await expect(page.getByText('CPython 3.13.7', { exact: true })).toBeVisible();
  await page.getByLabel('Exact work-target version ID').fill(revisionId);
  await page.getByLabel('Exact saved source version ID').fill(sourceRevisionId);
  await page.getByLabel('Source path and entrypoint').fill('main.py');
  await page
    .getByLabel('Additional exact inputs (optional)')
    .fill('INPUT data.json ARTIFACT aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');
  await page.getByLabel('Arguments (optional; one argv value per line)').fill('--mode\nproof');
  await page.getByRole('button', { name: 'Submit verification job' }).click();
  await expect(
    page.locator('section[aria-labelledby="verification-submit-title"] [role="alert"]'),
  ).toContainText('requested limits are retained');
  await page.getByRole('button', { name: 'Submit verification job' }).click();
  await expect(page).toHaveURL(`/projects/${projectId}/verification/${submittedJobId}`);

  expect(submissions).toHaveLength(2);
  expect(submissions[1]).toEqual(submissions[0]);
  expect(submissions[1]).toMatchObject({
    submission: {
      version: 1,
      project_id: projectId,
      work_target_object_version_id: revisionId,
      research_attempt_object_version_id: null,
      environment_id: environmentId,
      purpose: 'PYTHON_RUN',
      inputs: [
        { path: 'main.py', role: 'SOURCE', object_version_id: sourceRevisionId },
        {
          path: 'data.json',
          role: 'INPUT',
          artifact_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        },
      ],
      entrypoint: 'main.py',
      arguments: ['--mode', 'proof'],
      seed: null,
      limits,
    },
  });
});

test('project map opens with isolated objects and supports searchable focus', async ({ page }) => {
  const requests = await mock(page);
  await page.goto(`/projects/${projectId}/map`);
  await expect(page.getByLabel('Focus on an object', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: /^All objects/ })).toBeVisible();
  expect(requests.some((p) => p.includes('neighborhood'))).toBe(false);
  await expect(page.getByText('Select an object on the map to see its details.')).toBeVisible();
  await expect(
    page.getByRole('complementary', { name: 'Object details', exact: true }),
  ).toHaveCount(0);
  await expect(page.locator('.project-tools .tool-content .relationships')).toHaveCount(0);
  await page.getByLabel('Focus on an object', { exact: true }).fill('Spectral');
  await page
    .getByRole('list', { name: 'Focused object search results' })
    .getByRole('button')
    .first()
    .click();
  await expect(page.getByRole('heading', { name: /^Search results/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Clear focus' })).toBeVisible();
  expect(requests.filter((p) => p.includes('neighborhood'))).toHaveLength(0);
  await expect(
    page
      .locator('.project-tools .tool-content')
      .getByRole('link', { name: 'Open object', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Clear focus' }).click();
  await expect(page.getByRole('button', { name: 'Clear focus' })).toHaveCount(0);
  await expect(page.getByText('Select an object on the map to see its details.')).toBeVisible();
  await expect(
    page.getByRole('complementary', { name: 'Object details', exact: true }),
  ).toHaveCount(0);
  await expect(page.locator('.project-tools .tool-content .relationships')).toHaveCount(0);
  await page.getByLabel('Focus on an object', { exact: true }).fill('nonexistent');
  await expect(page.getByText('No matching objects. Try fewer terms.')).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-svelte-graph.png', fullPage: true });
});

test('project map renders connections and keeps every object when focused', async ({ page }) => {
  await mock(page);
  await mockProjectGraph(page, 3, 2);
  await page.goto(`/projects/${projectId}/map`);
  await expect(page.getByText('3 objects · 2 relationships', { exact: true })).toHaveCount(0);
  await expect(page.locator('.svelte-flow__node')).toHaveCount(3);
  await expect(page.locator('.svelte-flow__edge')).toHaveCount(2);
  const legend = page.getByRole('region', { name: 'Map legend' });
  await expect(legend).toBeVisible();
  await expect(legend.locator('[data-map-shape="oval"]')).toBeVisible();
  await expect(legend.locator('.map-legend-kind')).toHaveText([
    'Problem',
    'Definition',
    'Statement',
    'Proof',
  ]);
  await expect(legend).toContainText('Object → supporting object');
  await expect(legend).toContainText('Focused object');
  expect((await legend.boundingBox())!.y).toBeGreaterThan(
    (await page.locator('.graph').boundingBox())!.y,
  );
  const paths = page.locator('.svelte-flow__edge .svelte-flow__edge-path');
  await expect(paths.first()).toHaveAttribute('marker-end', /url/);
  expect(await paths.first().getAttribute('d')).not.toBe(await paths.last().getAttribute('d'));
  await expect(page.getByText('A → B: A depends on B.', { exact: false })).toHaveCount(0);
  await page.getByLabel('Focus on an object', { exact: true }).fill('"Statement 1"');
  await page
    .getByRole('list', { name: 'Focused object search results' })
    .getByRole('button')
    .click();
  await expect(page.locator('.svelte-flow__node')).toHaveCount(3);
  await expect(page.locator('.project-tools .tool-content')).toContainText('Statement 1');
  await expect(
    page
      .getByRole('complementary', { name: 'Object details', exact: true })
      .getByRole('heading', { name: 'Statement 1', exact: true }),
  ).toBeVisible();
  const panel = await projectInspector(page);
  const bodyTab = panel.getByRole('tab', { name: 'Body', exact: true });
  await expect(bodyTab).toHaveAttribute('aria-selected', 'true');
  await expect(panel.getByRole('tabpanel')).toContainText('Can we bound');
  await expect(panel.locator('.prose .katex').first()).toBeVisible();
  await bodyTab.focus();
  await bodyTab.press('ArrowRight');
  await expect(panel.getByRole('tab', { name: /^Relationships/ })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(panel.getByRole('tabpanel')).toContainText('Referenced by');
  await panel.getByRole('tab', { name: /^Relationships/ }).press('ArrowLeft');
  await expect(bodyTab).toHaveAttribute('aria-selected', 'true');
  await page.locator('.graph').scrollIntoViewIfNeeded();
  await page.screenshot({ path: '/tmp/polycolab-project-map.png', fullPage: true });
});

test('map hides equivalence and retains one node per object', async ({ page }) => {
  await mock(page);
  await mockProjectGraph(page, 2, 0);
  await page.route('**/api/v1/objects/*/relations**', (route) =>
    route.fulfill({
      json: {
        items: [
          {
            id: 'equivalence',
            direction: 'BIDIRECTIONAL',
            binding: 'DECLARATION',
            relationship_type: 'EQUIVALENT_TO',
            first_object_version_id: 'version-0',
            second_object_version_id: 'historical-1',
            description: null,
            ownership_scope_id: null,
            authorship: claimVersion().authorship,
            created_at: revision.created_at,
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.route('**/api/v1/objects/*/versions**', (route) =>
    route.fulfill({
      json: {
        items: [
          claimVersion({
            id: 'historical-1',
            object_id: 'object-1',
            number: 1,
            content: { ...object.current_object_version.content, title: 'Original statement' },
          }),
        ],
        next_cursor: null,
      },
    }),
  );
  await page.goto(`/projects/${projectId}/map`);
  await expect(page.locator('.svelte-flow__node')).toHaveCount(2);
  await expect(page.locator('.svelte-flow__edge')).toHaveCount(0);
  await page
    .getByRole('list', { name: 'All objects', exact: true })
    .getByRole('button', { name: 'Statement 0', exact: true })
    .click();
  const panel = page.getByRole('complementary', { name: 'Object details', exact: true });
  await panel.getByRole('tab', { name: /^Relationships/ }).click();
  await expect(panel.getByText('No relationships to show.')).toBeVisible();
});

test('map preserves viewport on selection, fits all, preserves search, and groups dependencies', async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mock(page);
  await mockProjectGraph(page, 6, 6);
  await page.goto(`/projects/${projectId}/map`);
  await page.getByRole('button', { name: 'Find object', exact: true }).click();
  const search = page.getByLabel('Focus on an object', { exact: true });
  await expect(search).toBeFocused();
  await search.fill('Statement');
  const results = page.getByRole('list', { name: 'Focused object search results' });
  await results.getByRole('button', { name: 'Statement 0', exact: true }).click();
  await expect(search).toHaveValue('Statement');
  await expect(results.getByRole('button')).toHaveCount(6);
  const panel = page.getByRole('complementary', { name: 'Object details', exact: true });
  await panel.getByRole('tab', { name: /^Relationships/ }).click();
  await expect(panel.getByRole('heading', { name: 'Depends on (1)', exact: true })).toBeVisible();
  await expect(
    panel.getByRole('heading', { name: 'Referenced by (1)', exact: true }),
  ).toBeVisible();
  await panel.getByText('Connection versions', { exact: true }).first().click();
  await expect(
    panel.locator('details').first().getByRole('link', { name: 'Statement 0 v1', exact: true }),
  ).toBeVisible();
  await expect(panel.locator('details').first()).not.toContainText('revision-0');
  const viewport = page.locator('.svelte-flow__viewport');
  const initialTransform = await viewport.evaluate((element) => element.getAttribute('style'));
  await results.getByRole('button', { name: 'Statement 5', exact: true }).click();
  await page.evaluate(
    () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
  );
  await expect(viewport).toHaveAttribute('style', initialTransform!);
  const graph = page.locator('.graph');
  await graph.scrollIntoViewIfNeeded();
  const selected = page.locator('.svelte-flow__node').filter({ hasText: 'Statement 5' });
  await page.getByRole('button', { name: 'Center focused object', exact: true }).click();
  await expect
    .poll(async () => {
      const bounds = (await graph.boundingBox())!;
      const node = (await selected.boundingBox())!;
      return Math.abs(node.x + node.width / 2 - bounds.x - bounds.width / 2);
    })
    .toBeLessThan(3);
  await page.getByRole('button', { name: 'Fit all', exact: true }).click();
  await expect
    .poll(async () => {
      const bounds = (await graph.boundingBox())!;
      return await page.locator('.svelte-flow__node').evaluateAll(
        (nodes, bounds) =>
          nodes.every((node) => {
            const r = node.getBoundingClientRect();
            return (
              r.left >= bounds.x &&
              r.right <= bounds.x + bounds.width &&
              r.top >= bounds.y &&
              r.bottom <= bounds.y + bounds.height
            );
          }),
        bounds,
      );
    })
    .toBe(true);
  await page.getByRole('button', { name: 'Center focused object', exact: true }).click();
  await expect(search).toHaveValue('Statement');
  await page.getByRole('button', { name: 'Clear search', exact: true }).click();
  await expect(
    page.getByRole('list', { name: 'All objects', exact: true }).getByRole('button'),
  ).toHaveCount(6);
});

test('map shows distinct object types consistently in nodes, cards, and the panel', async ({
  page,
}) => {
  await mock(page);
  await mockProjectGraph(page, 3, 2, ['STATEMENT', 'DEFINITION', 'PROOF'], true);
  await page.goto(`/projects/${projectId}/map`);
  await expect(page.getByRole('status').filter({ hasText: 'Loading project map' })).toHaveCount(0, {
    timeout: 20000,
  });
  for (const [index, kind, label, shape] of [
    [0, 'STATEMENT', 'Statement', 'hexagon'],
    [1, 'DEFINITION', 'Definition', 'card'],
    [2, 'PROOF', 'Proof', 'diamond'],
  ] as const) {
    const node = page.locator(`.svelte-flow__node[data-id="version-${index}"]`);
    await expect(node.locator('.object-node')).toHaveAttribute(
      'aria-label',
      `${label}: Statement ${index}`,
      { timeout: 20000 },
    );
    await expect(node.locator('[data-map-shape]')).toHaveAttribute('data-map-shape', shape);
    await expect
      .poll(async () =>
        node.locator('.object-node').evaluate((element) => {
          const bounds = element.getBoundingClientRect();
          const dot = element.querySelector('.progress-dot')!.getBoundingClientRect();
          return Math.max(
            Math.abs(dot.x + dot.width / 2 - (bounds.x + bounds.width * 0.99)),
            Math.abs(dot.y + dot.height / 2 - (bounds.y + bounds.height / 2)),
          );
        }),
      )
      .toBeLessThan(1);

    await expect(page.locator(`.object-list [data-object-kind="${kind}"]`)).toBeVisible();
  }
  const proofSize = (await page
    .locator('.svelte-flow__node[data-id="version-1"] .object-node')
    .boundingBox())!;
  const sketchSize = (await page
    .locator('.svelte-flow__node[data-id="version-2"] .object-node')
    .boundingBox())!;
  expect(sketchSize.width).toBeLessThan(proofSize.width);
  expect(sketchSize.width / proofSize.width).toBeCloseTo(2 / 3, 1);
  await expect(page.locator('.svelte-flow__node[data-id="version-2"] .object-title')).toHaveText(
    'Statement 2',
  );
  await page
    .getByRole('list', { name: 'All objects', exact: true })
    .getByRole('button', { name: 'Statement 2', exact: true })
    .click();
  const focusedShape = page.locator('.svelte-flow__node[data-id="version-2"] [data-map-shape]');
  await expect(focusedShape.locator('.focus-ring')).toBeVisible();
  await expect(focusedShape.locator('.focus-gap')).toBeVisible();
  const sketchStroke = await page
    .locator('.map-legend-kind')
    .filter({ hasText: 'Proof' })
    .locator('.kind-shape')
    .evaluate((shape) => getComputedStyle(shape).stroke);
  await expect(focusedShape.locator('.kind-shape')).toHaveCSS('stroke', sketchStroke);
  await expect(page.locator('.map-legend .focus-ring')).toBeVisible();
  await expect(
    page.locator('.project-tools .tool-content [data-object-kind="PROOF"]'),
  ).toBeVisible();
  const panel = await projectInspector(page);
  await expect(panel.getByRole('combobox', { name: 'Reported progress' })).toHaveCount(0);
  await panel.getByRole('tab', { name: 'Progress', exact: true }).click();
  await expect(panel.getByRole('combobox', { name: 'Reported progress' })).toHaveValue('PARTIAL');

  await page.locator('.graph').scrollIntoViewIfNeeded();
  await page.screenshot({ path: '/tmp/polycolab-object-types.png', fullPage: true });
});

test('map search and object cards live below the map while the panel inspects selection', async ({
  page,
}) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/map`);
  const main = page.locator('#main');
  const panel = await projectInspector(page);
  await expect(main.getByLabel('Focus on an object', { exact: true })).toBeVisible();
  await expect(main.getByRole('heading', { name: /^All objects/ })).toBeVisible();
  await expect(page.getByText('Browse all objects', { exact: true })).toHaveCount(0);
  const firstCard = main
    .getByRole('list', { name: 'All objects', exact: true })
    .getByRole('button')
    .first();
  await firstCard.click();
  await expect(firstCard).toHaveAttribute('aria-pressed', 'true');
  await expect(firstCard).toHaveClass(/selected/);
  await expect(main.getByRole('button', { name: 'Focus object', exact: true })).toHaveCount(0);
  await expect(panel.getByLabel('Focus on an object', { exact: true })).toHaveCount(0);
  await main.getByLabel('Focus on an object', { exact: true }).fill('Spectral');
  await main
    .getByRole('list', { name: 'Focused object search results' })
    .getByRole('button')
    .click();
  await expect(panel.getByRole('link', { name: 'Open object', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: /^(Show|Hide) tools$/ }).click();
  const drawer = page.getByRole('dialog', { name: 'Object details', exact: true });
  await expect(drawer.getByRole('link', { name: 'Open object', exact: true })).toBeVisible();
});

test('large project map renders its canvas and supports search focus', async ({ page }) => {
  await mock(page);
  await mockProjectGraph(page, 60, 80);
  await page.goto(`/projects/${projectId}/map`);
  await expect(page.locator('[data-dense-graph] canvas')).toBeVisible();
  await expect(page.getByText('60 objects · 80 relationships', { exact: true })).toHaveCount(0);
  await page.getByLabel('Focus on an object', { exact: true }).fill('"Statement 59"');
  await page
    .getByRole('list', { name: 'Focused object search results' })
    .getByRole('button')
    .click();
  await expect(page.locator('.project-tools .tool-content')).toContainText('Statement 59');
});

test('keeps the 200-node graph frame interval within budget', async ({ page }, testInfo) => {
  test.skip(
    !testInfo.config.metadata.productionBuild,
    'Graph measurements require a production build.',
  );
  await mock(page);
  await mockProjectGraph(page, 200, 600);
  await page.goto(`/projects/${projectId}/map`);
  const frameSamples = page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const samples: number[] = [];
        let previous = performance.now();
        const collect = (now: number) => {
          samples.push(now - previous);
          previous = now;
          if (samples.length === 120) resolve(samples);
          else requestAnimationFrame(collect);
        };
        requestAnimationFrame(collect);
      }),
  );

  await expect(page.getByRole('button', { name: 'Statement 99', exact: true })).toBeVisible();
  const samples = await frameSamples;
  const ordered = [...samples].sort((left, right) => left - right);
  const p95Ms = ordered[Math.ceil(ordered.length * 0.95) - 1];
  await testInfo.attach('frontend-graph-frames.json', {
    body: JSON.stringify(
      {
        p95Ms,
        samples,
        nodes: 200,
        edges: 600,
        environment:
          'Local production preview; mocked API; no CPU throttling. Graph has a complete readable relationship list.',
      },
      null,
      2,
    ),
    contentType: 'application/json',
  });
  expect(p95Ms).toBeLessThanOrEqual(20);
  await expect(page.getByRole('button', { name: 'Statement 199', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Show more objects' }).click();
  await expect(page.getByRole('button', { name: 'Statement 199', exact: true })).toBeVisible();
});

test('renders the separate 1,000-node graph stress case without an application error', async ({
  page,
}, testInfo) => {
  test.skip(
    !testInfo.config.metadata.productionBuild,
    'Graph measurements require a production build.',
  );
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await mock(page);
  await mockProjectGraph(page, 1000, 3000);
  await page.goto(`/projects/${projectId}/map`);

  // This stress case checks completion; the 200-node journey owns the frame budget.
  await expect(page.locator('[data-dense-graph] canvas')).toBeVisible({ timeout: 20_000 });
  await expect(
    page.getByText(/Overview of 1000 exact versions and 3000 relationships/),
  ).toBeAttached();
  const showNext = page.getByRole('button', { name: 'Show more objects' });
  for (let pageIndex = 1; pageIndex < 10; pageIndex += 1) await showNext.click();
  await expect(page.getByRole('button', { name: 'Statement 999', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('repeated project navigation stays responsive with layout modes and retained editor drafts', async ({
  page,
}) => {
  await mock(page);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(`/projects/${projectId}/research`);
  const navigation = page.getByRole('navigation', { name: 'Project sections', exact: true });
  await expect(
    page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }),
  ).toBeVisible();

  for (let index = 0; index < 6; index++) {
    await navigation.getByRole('link', { name: 'Map', exact: true }).click();
    await page.getByLabel('Focus on an object', { exact: true }).fill('Spectral');
    await page
      .getByRole('list', { name: 'Focused object search results' })
      .getByRole('button')
      .first()
      .click();
    await expect(page.locator('.svelte-flow')).toHaveCount(1);
    await navigation.getByRole('link', { name: 'Research objects', exact: true }).click();
    await expect(page.locator('.svelte-flow')).toHaveCount(0);

    await page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }).click();
    if (index === 0) await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.locator('textarea.editor')).toHaveCount(1);
    await expect(page.locator('textarea.editor')).toBeVisible();
    await page.locator('textarea.editor').fill(`Retained draft ${index}`);
    await navigation.getByRole('link', { name: 'Activity', exact: true }).click();
    await expect(page.locator('textarea.editor')).toBeHidden();
    await navigation.getByRole('link', { name: 'Project', exact: true }).click();
    await page.getByRole('button', { name: 'New chat tab', exact: true }).click();
    await expect(page.getByLabel('Message the agent').filter({ visible: true })).toBeVisible();
    await page
      .getByLabel('Message the agent')
      .filter({ visible: true })
      .fill(`Chat draft ${index}`);
    await navigation.getByRole('link', { name: 'Research objects', exact: true }).click();
    await expect(page.locator('.svelte-flow')).toHaveCount(0);
    await expect(page.locator('textarea.editor')).toHaveValue(`Retained draft ${index}`);
    expect(errors).toEqual([]);
  }
});

test('owner settings are reachable and save details without changing visibility', async ({
  page,
}) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/settings`);
  await expect(page.getByRole('heading', { name: 'Project settings', level: 1 })).toBeVisible();
  const settings = page.locator('.settings-stack');
  await expect(settings.getByRole('heading', { level: 2 })).toHaveText([
    'Project details',
    'Members',
    'Project lifecycle',
  ]);
  await expect(settings.locator('.settings-section')).toHaveCount(3);
  await page.screenshot({ path: '/tmp/polycolab-project-settings.png', fullPage: true });
  await page.getByLabel('Name', { exact: true }).fill('Revised name');
  const request = page.waitForRequest((r) => r.method() === 'PATCH');
  await page.getByRole('button', { name: 'Save settings' }).click();
  expect((await request).postDataJSON()).toEqual({
    name: 'Revised name',
    description: project.description,
  });
  await expect(page.getByRole('status')).toContainText('Settings saved');
});

test('project owners add registered collaborators by exact username', async ({ page }) => {
  await mock(page);
  const ada = {
    user_id: '11111111-1111-4111-8111-111111111111',
    username: 'ada',
    display_name: 'Ada Lovelace',
    role: 'OWNER',
    created_at: revision.created_at,
  };
  const grace = {
    user_id: '22222222-2222-4222-8222-222222222222',
    username: 'grace.hopper',
    display_name: 'Grace Hopper',
    role: 'CONTRIBUTOR',
    created_at: revision.created_at,
  };
  let listed = [ada];
  const additions: Record<string, unknown>[] = [];
  const memberMutations: Array<{ method: string; body?: Record<string, unknown> }> = [];
  await page.route(
    new RegExp(`/api/v1/projects/${projectId}/members(?:\\?.*)?$`),
    async (route) => {
      const request = route.request();
      if (request.method() === 'GET') return route.fulfill({ json: listed });
      const body = request.postDataJSON() as Record<string, unknown>;
      additions.push(body);
      if (body.username === 'missing.user')
        return route.fulfill({ status: 400, json: { error: { code: 'invalid_member' } } });
      if (listed.some((member) => member.username === body.username))
        return route.fulfill({ status: 409, json: { error: { code: 'conflict' } } });
      listed = [...listed, grace];
      return route.fulfill({ status: 201, json: grace });
    },
  );
  await page.route(`**/api/v1/projects/${projectId}/members/${grace.user_id}`, async (route) => {
    const request = route.request();
    if (request.method() === 'DELETE') {
      memberMutations.push({ method: 'DELETE' });
      listed = listed.filter((member) => member.user_id !== grace.user_id);
      return route.fulfill({ status: 204 });
    }
    const body = request.postDataJSON() as Record<string, unknown>;
    memberMutations.push({ method: request.method(), body });
    const updated = { ...grace, role: String(body.role) };
    listed = listed.map((member) => (member.user_id === grace.user_id ? updated : member));
    return route.fulfill({ json: updated });
  });
  await page.route(`**/api/v1/projects/${projectId}/members/${ada.user_id}`, (route) =>
    route.fulfill({ status: 409, json: { error: { code: 'conflict' } } }),
  );

  await page.goto(`/projects/${projectId}/settings`);
  await expect(page.getByText('Ada Lovelace', { exact: true })).toBeVisible();
  await expect(page.getByText('@ada', { exact: true })).toBeVisible();
  await expect(page.getByLabel('User ID')).toHaveCount(0);
  await expect(page.getByLabel('Email')).toHaveCount(0);

  await page.getByLabel('Exact username').fill('Grace.Hopper');
  await expect(page.getByLabel('Member role').locator('option[value="READ_ONLY"]')).toHaveCount(0);
  await page.getByLabel('Member role').selectOption('CONTRIBUTOR');
  await page.getByRole('button', { name: 'Add member' }).click();
  await expect(page.getByRole('status')).toHaveText('Member added.');
  await expect(page.getByText('Grace Hopper', { exact: true })).toBeVisible();
  expect(additions[0]).toEqual({ username: 'grace.hopper', role: 'CONTRIBUTOR' });

  const owner = page.getByRole('listitem').filter({ hasText: 'Ada Lovelace' });
  await owner.getByLabel('Role').selectOption('CONTRIBUTOR');
  await expect(page.getByRole('alert')).toContainText('retain at least one owner');

  const collaborator = page.getByRole('listitem').filter({ hasText: 'Grace Hopper' });
  await collaborator.getByLabel('Role').selectOption('OWNER');
  await expect(page.getByRole('status')).toHaveText('Role updated.');
  expect(memberMutations).toEqual([{ method: 'PATCH', body: { role: 'OWNER' } }]);

  await page.getByLabel('Exact username').fill('missing.user');
  await page.getByRole('button', { name: 'Add member' }).click();
  await expect(page.getByRole('alert')).toContainText('No account matches that exact username');

  await page.getByLabel('Exact username').fill('grace.hopper');
  await page.getByRole('button', { name: 'Add member' }).click();
  await expect(page.getByRole('alert')).toContainText('already a member');

  await collaborator.getByRole('button', { name: 'Remove' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(page.getByText('Grace Hopper', { exact: true })).toHaveCount(0);
  expect(memberMutations.at(-1)).toEqual({ method: 'DELETE' });
});

test('provider keys remain write-only across create, validation, rotation, failure and deletion', async ({
  page,
}) => {
  await mock(page);
  const original = {
    api_key_preview: null as string | null,
    id: 'profile-1',
    display_name: 'Research model',
    base_url: 'https://example.com/v1',
    model_id: 'test-model',
  };
  let profiles = [original];
  let failCreate = false;
  const writes: Array<{ path: string; body?: Record<string, string> }> = [];
  await page.route('**/api/v1/gateway/profiles**', async (route) => {
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
    if (request.method() === 'GET') return route.fulfill({ json: profiles });
    const body = request.postData() ? (request.postDataJSON() as Record<string, string>) : null;
    writes.push({ path, body: body ?? undefined });
    if (path === '/api/v1/gateway/profiles' && failCreate)
      return route.fulfill({
        status: 503,
        json: { error: { code: 'credential_unavailable' } },
      });
    if (path === '/api/v1/gateway/profiles' && request.method() === 'POST') {
      const created = {
        api_key_preview: 'cre••••cret',
        id: 'profile-2',
        display_name: body!.display_name!,
        base_url: body!.base_url!,
        model_id: body!.model_id!,
      };
      profiles = [...profiles, created];
      return route.fulfill({ status: 201, json: created });
    }
    const profile = profiles.find((item) => path.includes(item.id));
    if (path.endsWith('/rotate') && profile) profile.api_key_preview = 'rot••••cret';
    if (path.endsWith('/validate') || path.endsWith('/rotate'))
      return route.fulfill({ json: profile });
    if (request.method() === 'DELETE') {
      profiles = profiles.filter((item) => item.id !== profile?.id);
      return route.fulfill({ status: 204 });
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } });
  });

  await page.goto('/settings/model-providers');
  await expect(page.getByRole('heading', { name: 'Model providers' })).toBeVisible();
  await expect(page.getByText('Preview unavailable', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Display name')).toHaveCount(0);
  await page.getByRole('button', { name: 'Add model provider' }).click();
  await expect(page.getByLabel('Display name')).toBeFocused();
  await page.getByLabel('Display name').fill('Second model');
  await page.getByLabel('API endpoint').fill('https://second.example/v1');
  await page.getByLabel('Model ID').fill('second-model');
  await page.getByLabel('API key').fill('create-secret');
  await page.getByRole('button', { name: 'Save provider' }).click();
  await expect(page.getByRole('status')).toHaveText('AI provider added.');
  await expect(page.getByText('Second model', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);

  const second = page.getByRole('row').filter({ hasText: 'Second model' });
  await expect(page.getByRole('table', { name: 'Your model providers' })).toBeVisible();
  await page.getByLabel('Search loaded model providers').fill('second-model');
  await expect(second).toBeVisible();
  await expect(page.getByText('Research model', { exact: true })).toHaveCount(0);
  await page.getByLabel('Search loaded model providers').fill('no-match');
  await expect(page.getByText('No matching providers in the loaded results.')).toBeVisible();
  await page.getByLabel('Search loaded model providers').clear();
  await expect(second.getByText('cre••••cret', { exact: true })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('create-secret');
  await expect(second.getByText('Not tested')).toBeVisible();
  const tableBounds = await page.getByRole('table', { name: 'Your model providers' }).boundingBox();
  await page.getByRole('button', { name: 'Dismiss notification' }).click();
  expect(await page.getByRole('table', { name: 'Your model providers' }).boundingBox()).toEqual(
    tableBounds,
  );
  await second.getByRole('button', { name: 'Actions for Second model' }).click();
  await page.getByRole('menuitem', { name: 'Test connection' }).click();
  await expect(page.getByRole('status')).toHaveText('Connection to Second model verified.');
  await expect(second.getByText('Connection verified')).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-providers-desktop.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(second.getByRole('button', { name: 'Actions for Second model' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: '/tmp/polycolab-providers-mobile.png' });
  await second.getByRole('button', { name: 'Actions for Second model' }).click();
  await page.getByRole('menuitem', { name: 'Replace API key' }).click();
  await page.getByLabel('Replacement key').fill('rotation-secret');
  await page.getByRole('button', { name: 'Save replacement' }).click();
  await expect(page.getByRole('status')).toHaveText('API key replaced.');
  await expect(page.getByLabel('Replacement key')).toHaveCount(0);
  await expect(second.getByText('rot••••cret', { exact: true })).toBeVisible();
  await expect(second.getByText('cre••••cret', { exact: true })).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('rotation-secret');

  await expect(second.getByText('Not tested')).toBeVisible();
  failCreate = true;
  await page.getByRole('button', { name: 'Add model provider' }).click();
  await expect(page.getByLabel('Display name')).toBeFocused();
  await page.getByLabel('Display name').fill('Unavailable key service');
  await page.getByLabel('API endpoint').fill('https://failure.example/v1');
  await page.getByLabel('Model ID').fill('failure-model');
  await page.getByLabel('API key').fill('retained-secret');
  const inputBounds = await page.getByLabel('API key').boundingBox();
  await page.getByRole('button', { name: 'Save provider' }).click();
  await expect(page.getByRole('alert')).toContainText('secure key service is unavailable');
  await expect(page.getByLabel('API key')).toHaveValue('retained-secret');
  expect(await page.getByLabel('API key').boundingBox()).toEqual(inputBounds);
  await page.screenshot({ path: '/tmp/polycolab-provider-error-toast.png' });
  expect(await page.locator('body').textContent()).not.toContain('retained-secret');

  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Add model provider' }).click();
  await expect(page.getByLabel('API key')).toHaveValue('');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await second.getByRole('button', { name: 'Actions for Second model' }).click();
  await page.getByRole('menuitem', { name: 'Delete provider' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('AI provider deleted.');
  await expect(page.getByText('Second model', { exact: true })).toHaveCount(0);
  expect(writes).toEqual(
    expect.arrayContaining([
      {
        path: '/api/v1/gateway/profiles',
        body: expect.objectContaining({ api_key: 'create-secret' }),
      },
      {
        path: '/api/v1/gateway/profiles/profile-2/rotate',
        body: { api_key: 'rotation-secret' },
      },
      { path: '/api/v1/gateway/profiles/profile-2', body: undefined },
    ]),
  );
});

test('proposal conflict keeps edits and batch retry identity', async ({ page }) => {
  await mock(page);
  const proposalId = '66666666-6666-4666-8666-666666666666';
  const bodies: unknown[] = [];
  const keys: (string | undefined)[] = [];
  let contextPrivate = false;
  await page.route(`**/api/v1/proposals/${proposalId}/context`, (route) =>
    contextPrivate
      ? route.fulfill({ status: 404, json: { error: { code: 'not_found' } } })
      : route.fulfill({
          json: {
            id: 'context-1',
            run_id: runId,
            project_id: projectId,
            object_version_ids: [revisionId],
            artifact_ids: ['artifact-exact-1'],
            digest: 'd'.repeat(64),
            created_at: revision.created_at,
            object_versions: [
              claimVersion({
                id: revisionId,
                object_id: objectId,
                content: {
                  title: revision.title,
                  content_md: revision.content_md,
                  assumptions_md: 'None',
                  reported_outcome: null,
                  explanation_md: null,
                },
              }),
            ],
          },
        }),
  );
  await page.route(`**/api/v1/proposals/${proposalId}`, (route) =>
    route.fulfill({
      json: {
        id: proposalId,
        project_id: projectId,
        summary: 'A proposed bound',
        agent_version_id: 'agent-1',
        context_manifest_id: 'context-1',
        created_at: revision.created_at,
        changes: [
          {
            id: 'change-1',
            ordinal: 1,
            change_type: 'CREATE_REVISION',
            status: 'PENDING',
            payload: {
              kind: 'CREATE_OBJECT_VERSION',
              object_id: objectId,
              expected_current_object_version_id: revisionId,
              snapshot: {
                kind: 'STATEMENT',
                content: {
                  title: revision.title,
                  content_md: 'Proposed argument',
                  assumptions_md: 'Finite graphs',
                  reported_outcome: null,
                  explanation_md: null,
                },
                structural_relationships: [
                  { relationship_type: 'ATTACHMENT', target_object_version_id: revisionId },
                ],
                change_summary: null,
              },
            },
            applied_entity_id: null,
            decided_at: null,
            decided_by_user_id: null,
            rejection_reason: null,
          },
        ],
      },
    }),
  );
  await page.route(`**/api/v1/proposals/${proposalId}/decisions`, (route) => {
    bodies.push(route.request().postDataJSON());
    keys.push(route.request().headers()['idempotency-key']);
    return route.fulfill({ status: 409, json: { error: { code: 'stale_revision' } } });
  });
  await page.goto(`/projects/${projectId}/proposals/${proposalId}`);
  const sourceContext = page.getByRole('region', { name: 'Proposal source context' });
  await expect(
    sourceContext.getByRole('heading', { name: 'Exact object versions supplied to the agent' }),
  ).toBeVisible();
  await expect(sourceContext).toContainText('Exact source');
  await expect(sourceContext).toContainText('artifact-exact-1');
  await expect(sourceContext.getByText(revision.content_md)).toBeHidden();
  await sourceContext.getByText('Show source content').click();
  await expect(sourceContext.getByText(revision.content_md)).toBeVisible();
  await page.getByRole('checkbox', { name: 'Select change 1' }).check();
  await page.getByRole('button', { name: 'Apply 1 selected decisions' }).click();
  await expect(page.getByRole('alert')).toContainText('draft is retained');
  expect(bodies).toEqual([{ decisions: [{ change_id: 'change-1', action: 'ACCEPT' }] }]);
  const unchangedKey = keys[0];
  bodies.length = 0;
  keys.length = 0;
  await page.getByLabel('Research text (Markdown)').fill('My edited argument');
  await page.getByRole('button', { name: 'Apply 1 selected decisions' }).click();
  await expect(page.getByRole('alert')).toContainText('draft is retained');
  await expect(page.getByLabel('Research text (Markdown)')).toHaveValue('My edited argument');
  await page.getByRole('button', { name: 'Apply 1 selected decisions' }).click();
  expect(keys[0]).toBe(keys[1]);
  expect(keys[0]).not.toBe(unchangedKey);
  expect(bodies).toHaveLength(2);
  expect(bodies[0]).toEqual(bodies[1]);
  expect(bodies[0]).toMatchObject({
    decisions: [
      {
        payload: {
          kind: 'CREATE_OBJECT_VERSION',
          expected_current_object_version_id: revisionId,
          snapshot: {
            content: {
              content_md: 'My edited argument',
              assumptions_md: 'Finite graphs',
              reported_outcome: null,
              explanation_md: null,
            },
            structural_relationships: [
              { relationship_type: 'ATTACHMENT', target_object_version_id: revisionId },
            ],
            change_summary: null,
          },
        },
      },
    ],
  });

  contextPrivate = true;
  await page.reload();
  await expect(
    page.getByRole('heading', { name: 'Sources private to requesting contributor' }),
  ).toBeVisible();
  await expect(page.getByText(revision.content_md)).toHaveCount(0);
  await expect(page.getByRole('checkbox', { name: 'Select change 1' })).toBeVisible();
});

test('records production startup and cached-navigation timings', async ({ page }, testInfo) => {
  test.skip(
    !testInfo.config.metadata.productionBuild,
    'Bundle measurements require a production build.',
  );
  const { gzipSync } = await import('node:zlib');
  await mock(page);
  const scripts = new Map<string, Promise<number>>();
  page.on('response', (response) => {
    if (response.request().resourceType() === 'script')
      scripts.set(
        response.url(),
        response
          .body()
          .then((body) => gzipSync(body).length)
          .catch(() => 0),
      );
  });
  const start = Date.now();
  await page.goto('/projects');
  await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toBeVisible();
  const homeMs = Date.now() - start;
  const homeJsGzip = (await Promise.all(scripts.values())).reduce((a, b) => a + b, 0);
  await page.getByRole('link', { name: 'Spectral gaps', exact: true }).click();
  await page
    .getByRole('navigation', { name: 'Project sections' })
    .getByRole('link', { name: 'Research objects', exact: true })
    .click();
  await page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }).click();
  await expect(page.locator('#main').getByRole('heading', { name: revision.title })).toBeVisible();
  const times: number[] = [];
  for (let i = 0; i < 10; i++) {
    await page.getByRole('link', { name: 'Research objects', exact: true }).first().click();
    await expect(
      page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }),
    ).toBeVisible();
    const before = Date.now();
    await page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }).click();
    await expect(
      page.locator('#main').getByRole('heading', { name: revision.title }),
    ).toBeVisible();
    times.push(Date.now() - before);
  }
  times.sort((a, b) => a - b);
  await testInfo.attach('frontend-performance.json', {
    body: JSON.stringify(
      {
        homeMs,
        homeJsGzip,
        cachedNavigationP95Ms: times[9],
        samples: times,
        environment:
          'Local production preview; mocked API; no network/CPU throttling. Playwright timings include automation overhead.',
      },
      null,
      2,
    ),
    contentType: 'application/json',
  });
  expect(homeJsGzip).toBeLessThan(180_000);
  expect(times[9]).toBeLessThan(150);
});

test('keeps typing, selection, and control feedback within budget', async ({ page }, testInfo) => {
  test.skip(
    !testInfo.config.metadata.productionBuild,
    'Interaction measurements require a production build.',
  );
  await mock(page);
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  const editor = page.getByLabel('Markdown', { exact: true });
  await expect(editor).toBeVisible();

  const typingSamples: number[] = [];
  for (let index = 0; index < 20; index++) {
    const startedAt = performance.now();
    await editor.press(String.fromCharCode(97 + (index % 26)));
    await expect(editor).toHaveValue(new RegExp(`${String.fromCharCode(97 + (index % 26))}$`));
    typingSamples.push(performance.now() - startedAt);
  }

  const selectionSamples: number[] = [];
  for (let index = 0; index < 10; index++) {
    const statementStartedAt = performance.now();
    await page.getByRole('button', { name: 'Body', exact: true }).click();
    await expect(page.getByRole('link', { name: /Read typed record details/ })).toBeVisible();
    selectionSamples.push(performance.now() - statementStartedAt);
    const editStartedAt = performance.now();
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(editor).toBeVisible();
    selectionSamples.push(performance.now() - editStartedAt);
  }

  const controlSamples: number[] = [];
  for (let index = 0; index < 10; index++) {
    const collapseStartedAt = performance.now();
    await page.getByRole('button', { name: 'Collapse tools', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Show tools', exact: true })).toBeVisible();
    controlSamples.push(performance.now() - collapseStartedAt);
    const expandStartedAt = performance.now();
    await page.getByRole('button', { name: 'Show tools', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Collapse tools', exact: true })).toBeVisible();
    controlSamples.push(performance.now() - expandStartedAt);
  }

  const p95 = (samples: number[]) => {
    const ordered = [...samples].sort((left, right) => left - right);
    return ordered[Math.ceil(ordered.length * 0.95) - 1];
  };
  const measurements = {
    typingP95Ms: p95(typingSamples),
    selectionP95Ms: p95(selectionSamples),
    controlP95Ms: p95(controlSamples),
    typingSamples,
    selectionSamples,
    controlSamples,
    environment:
      'Local production preview; mocked API; no network/CPU throttling. Timings include Playwright automation overhead.',
  };
  await testInfo.attach('frontend-interaction-feedback.json', {
    body: JSON.stringify(measurements, null, 2),
    contentType: 'application/json',
  });
  expect(measurements.typingP95Ms).toBeLessThan(100);
  expect(measurements.selectionP95Ms).toBeLessThan(100);
  expect(measurements.controlP95Ms).toBeLessThan(100);
});

test('keeps cold primary content within budget at 100 ms API latency and 10 Mbps', async ({
  page,
  browserName,
}, testInfo) => {
  test.skip(
    !testInfo.config.metadata.productionBuild,
    'Bundle measurements require a production build.',
  );
  test.skip(browserName !== 'chromium', 'Network shaping uses Chromium DevTools.');
  const os = await import('node:os');
  await mock(page, 'OWNER', 100);
  await page.addInitScript(() => sessionStorage.removeItem('polycolab.auth-configuration.v1'));
  const devtools = await page.context().newCDPSession(page);
  await devtools.send('Network.enable');
  await devtools.send('Network.emulateNetworkConditions', {
    offline: false,
    latency: 0,
    downloadThroughput: (10 * 1024 * 1024) / 8,
    uploadThroughput: (10 * 1024 * 1024) / 8,
    connectionType: 'cellular4g',
  });

  const samples: number[] = [];
  for (let index = 0; index < 10; index++) {
    await devtools.send('Network.clearBrowserCache');
    await page.goto('about:blank');
    const startedAt = performance.now();
    await page.goto('/projects');
    await expect(page.getByRole('link', { name: 'Spectral gaps', exact: true })).toBeVisible();
    samples.push(performance.now() - startedAt);
  }
  samples.sort((left, right) => left - right);
  const p95Ms = samples[9];
  await testInfo.attach('frontend-throttled-cold-load.json', {
    body: JSON.stringify(
      {
        p95Ms,
        samples,
        apiLatencyMs: 100,
        connectionMbps: 10,
        environment: {
          cpu: os.cpus()[0]?.model,
          logicalCores: os.cpus().length,
          memoryBytes: os.totalmem(),
          platform: os.platform(),
          architecture: os.arch(),
          node: process.version,
          service: 'Local production preview with mocked API responses',
        },
      },
      null,
      2,
    ),
    contentType: 'application/json',
  });
  expect(p95Ms).toBeLessThan(2_000);
});

test('document honors exact-version links across reload and rejects unrelated versions', async ({
  page,
}) => {
  await mock(page);
  const old = claimVersion({
    id: 'old-version',
    object_id: objectId,
    number: 1,
    previous_object_version_id: null,
    content: {
      ...claimVersion().content,
      title: 'Historical formulation',
      content_md: 'Historical body',
    },
  });
  await page.route('**/api/v1/versions/*', (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1);
    if (id === 'missing')
      return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } });
    return route.fulfill({
      json: { ...old, object_id: id === 'unrelated' ? 'another-object' : objectId },
    });
  });
  await page.goto(`/projects/${projectId}/objects/${objectId}?revision=old-version`);
  await expect(
    page.getByRole('heading', { name: 'Historical formulation', exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole('heading', { name: 'Historical formulation', exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Return to current version' }).click();
  await expect(
    page.getByRole('heading', { name: revision.title, exact: true, level: 1 }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.has('revision')).toBe(false);
  await page.route(`**/api/v1/objects/${objectId}/versions**`, (route) =>
    route.fulfill({ json: { items: [old], next_cursor: null } }),
  );
  await page.getByRole('button', { name: 'History', exact: true }).click();
  await page.getByRole('button', { name: 'Read version 1', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: 'Historical formulation', exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.get('revision')).toBe('old-version');
  for (const id of ['missing', 'unrelated']) {
    await page.goto(`/projects/${projectId}/objects/${objectId}?revision=${id}`);
    await expect(page.getByRole('button', { name: 'Retry exact version' })).toBeVisible();
    await expect(
      page.getByRole('heading', { name: revision.title, exact: true, level: 1 }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('heading', { name: 'Historical formulation', exact: true }),
    ).toHaveCount(0);
  }
});

test('document workbench resizes panels and exposes details on mobile', async ({ page }) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await expect(
    page.locator('#main').getByRole('heading', { name: revision.title, exact: true }),
  ).toBeVisible();
  const resize = page.getByRole('separator', { name: 'Resize left panel', exact: true });
  await resize.press('ArrowRight');
  await expect(resize).toHaveAttribute('aria-valuenow', '268');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Hide left panel', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Worktrees', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close drawer' }).click();
  await page.getByRole('button', { name: 'Hide tools', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'Project tools', exact: true });
  await drawer.getByRole('tab', { name: 'Details', exact: true }).click();
  await expect(drawer.getByRole('tab', { name: 'Body', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('developer documentation renders the reusable Zensical components', async ({ page }) => {
  await page.goto('/docs/developers/components/');
  await expect(page.getByRole('heading', { name: 'Documentation components' })).toBeVisible();
  await expect(page.locator('.grid > .card')).toHaveCount(2);
  await expect(page.locator('.md-button--primary')).toHaveAttribute('href', '/docs/api');
  await expect(page.locator('.admonition')).toHaveCount(5);
  await expect(page.locator('details')).toHaveCount(2);
  await expect(page.locator('.task-list')).toBeVisible();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.locator('.tabbed-set')).toBeVisible();
  await page.getByText('Python', { exact: true }).click();
  await expect(page.locator('.tabbed-set input').nth(1)).toBeChecked();
  await expect(page.getByRole('button', { name: 'Copy to clipboard' }).first()).toBeVisible();
  await expect(
    page.locator('abbr[title="Application programming interface"]').first(),
  ).toBeVisible();
  await expect(page.locator('.footnote-ref')).toBeVisible();
  await expect(page.locator('figure figcaption')).toContainText('connected, attributable research');
  await expect(page.locator('.mermaid')).toBeVisible();
});

test('API reference retains the focused docs navigation on desktop and mobile', async ({
  page,
}) => {
  const loaderResponse = await page.request.get('/docs/scripts/api-reference.js');
  expect(loaderResponse.ok()).toBe(true);
  const loader = await loaderResponse.text();
  expect(loader).toContain('window.Scalar.createApiReference(container, {');
  expect(loader).toContain('--refs-header-height: 64px');
  expect(loader).toContain('darkMode');
  expect(loader).toContain("heading.slug === 'start-here' ? ''");
  expect(loader).not.toContain('forceDarkModeState');
  expect(loader).not.toContain("fetch('/api/reference/config'");
  await page.route('**/docs/scripts/api-reference.js', (route) =>
    route.fulfill({
      contentType: 'application/javascript',
      body: loader.replace(/\n {2}scalar\.integrity = '[^']+';/, ''),
    }),
  );
  await page.route('**/@scalar/api-reference@1.62.6/**', (route) =>
    route.fulfill({
      contentType: 'application/javascript',
      body: `window.Scalar = { createApiReference(container, configuration) {
        container.innerHTML = '<main data-scalar-dark="' + configuration.darkMode +
          '" style="min-height: 1400px"><h1>API endpoints</h1></main>';
        history.replaceState(null, '', configuration.generateHeadingSlug({ slug: 'start-here' }));
        return { unmount() {} };
      } };`,
    }),
  );
  await page.emulateMedia({ colorScheme: 'light' });
  await page.goto('/docs/api/');
  await expect(page).toHaveURL(/\/docs\/api\/$/);
  await expect(page.getByRole('navigation', { name: 'Documentation header' })).toBeVisible();
  await expect(page.locator('header.product-header')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'API endpoints' })).toBeVisible();
  await expect(page.locator('[data-scalar-dark]')).toHaveAttribute('data-scalar-dark', 'false');
  await page.locator('label[title="Use dark mode"]').click();
  await expect(page.locator('[data-scalar-dark]')).toHaveAttribute('data-scalar-dark', 'true');
  await expect(page.locator('iframe')).toHaveCount(0);
  await page.locator('.md-search__button').click();
  await page.getByRole('combobox').fill('credential');
  await expect(page.locator('div[style*="position: fixed"] a').first()).toBeVisible();
  await page.keyboard.press('Escape');
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 844, height: 390 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      viewport.width,
    );
    if (viewport.width === 1440) {
      await page.screenshot({ path: '/tmp/polycolab-api-reference.png' });
    }
    await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
    expect(await page.evaluate(() => scrollY)).toBeGreaterThan(0);
    expect(Math.round((await page.locator('header.polycolab-docs-header').boundingBox())!.y)).toBe(
      0,
    );
    await expect(page.locator('header.polycolab-docs-header')).toHaveCSS('z-index', '20');
  }
  await page.evaluate(() => scrollTo(0, 0));
  await page.locator('label.md-header__button[for="__drawer"]').click();
  await page
    .locator('.md-sidebar--primary')
    .getByRole('link', { name: 'Index', exact: true })
    .click();
  await expect(page).toHaveURL(/\/docs\/$/);
  await expect(page.getByRole('heading', { name: 'Index', exact: true })).toBeVisible();
});

test('shared controls retain responsive layout and keyboard dialog dismissal', async ({ page }) => {
  await mock(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/projects');
    await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    const trigger = page.getByRole('button', { name: 'New project', exact: true });
    await trigger.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByLabel('Project name', { exact: true })).toBeVisible();
    await dialog
      .getByLabel('Project name', { exact: true })
      .fill('A long research question that spans several lines on a phone');
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
      true,
    );
    await page.screenshot({ path: `/tmp/polycolab-ui-dialog-${width}.png` });
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  }
});

test('Library shows admitted statements at its own route and survives reload', async ({ page }) => {
  await mock(page);
  const entry = {
    entry_id: 'admitted-statement',
    object_version: claimVersion({
      object_id: 'admitted-statement',
      id: revisionId,
      kind: 'STATEMENT',
      content: {
        ...claimVersion().content,
        title: 'Reviewed catalogue statement',
        content_md: 'Official formulation.',
        assumptions_md: 'Finite graphs.',
      },
    }),
    source: { identifier: 'Source book', version: 'v1', locator: 'Theorem 2' },
    reported_status: 'Open',
    admitted_at: revision.created_at,
  };
  await page.route('**/api/v1/catalogue**', (route) =>
    route.fulfill({
      json: new URL(route.request().url()).pathname.endsWith('/admitted-statement')
        ? entry
        : { items: [entry], next_cursor: null },
    }),
  );
  await page.route('**/api/v1/library**', (route) =>
    route.fulfill({ json: { items: [entry], next_cursor: null } }),
  );
  await page.goto('/library');
  await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Spectral gaps' })).toHaveCount(0);
  await page.getByRole('link', { name: entry.object_version.content.title }).click();
  await expect(page).toHaveURL(/\/library\/admitted-statement$/);
  await page.reload();
  await expect(
    page.getByRole('heading', { name: entry.object_version.content.title }),
  ).toBeVisible();
  await expect(page).toHaveTitle(`${entry.object_version.content.title} · Polycolab`);
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('link', { name: 'Projects', exact: true })
    .click();
  await expect(page).toHaveURL(/\/projects$/);
  await page.getByRole('link', { name: 'Spectral gaps' }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
  await expect(page).toHaveTitle('Spectral gaps · Polycolab');
});

test('adds a sourced statement from Library and opens its saved formulation', async ({ page }) => {
  await mock(page);
  let saved: Record<string, unknown> | undefined;
  await page.route('**/api/v1/catalogue**', (route) =>
    route.fulfill({
      json: new URL(route.request().url()).pathname.endsWith('/new-entry')
        ? {
            entry_id: 'new-entry',
            object_version: {
              ...claimVersion(),
              object_id: 'new-entry',
              id: revisionId,
              kind: saved?.kind,
              content: { ...claimVersion().content, ...saved },
            },
            source: saved?.source,
            reported_status: saved?.reported_status,
            admitted_at: revision.created_at,
          }
        : { items: [], next_cursor: null },
    }),
  );
  await page.route('**/api/v1/catalogue', (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().headers()['idempotency-key']).toBeTruthy();
    saved = route.request().postDataJSON();
    return route.fulfill({
      status: 201,
      json: { entry_id: 'new-entry', object_version_id: revisionId },
    });
  });
  await page.goto('/library');
  await page.getByRole('link', { name: 'Add to Library' }).click();
  await expect(page).toHaveURL(/\/library\/new$/);
  await page.getByLabel('Title', { exact: true }).fill('A sourced theorem');
  await page.getByLabel('Formulation', { exact: true }).fill('Every finite tree has a leaf.');
  await page.getByLabel('Assumptions', { exact: true }).fill('At least two vertices.');
  await page.getByLabel('Source identifier').fill('Graph theory textbook');
  await page.getByLabel('Source version').fill('Second edition');
  await page.getByLabel('Source locator').fill('Theorem 1.2');
  await page.getByRole('button', { name: 'Preview entry' }).click();
  await page.getByRole('button', { name: 'Add to Library', exact: true }).click();
  await expect(page).toHaveURL(/\/library\/new-entry$/);
  await expect(page.getByRole('heading', { name: 'A sourced theorem' })).toBeVisible();
  await page.reload();
  await expect(page.getByText('Every finite tree has a leaf.')).toBeVisible();
});

test('project category controls adapt to viewport and preserve selection', async ({ page }) => {
  await mock(page);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto('/projects');
  const tabs = page.getByRole('navigation', { name: 'Project categories' });
  const dropdown = page.getByRole('combobox', { name: 'Project category', includeHidden: true });
  await expect(tabs).toBeVisible();
  await expect(dropdown).toBeHidden();
  await tabs.getByRole('button', { name: 'Owned', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(tabs).toBeHidden();
  await expect(dropdown).toBeVisible();
  await expect(dropdown).toHaveValue('owned');
  await dropdown.selectOption('shared');
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(dropdown).toBeHidden();
  await expect(tabs.getByRole('button', { name: 'Shared', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
});

for (const width of [1440, 1024, 390]) {
  test(`project rail and panels fit a ${width}px viewport`, async ({ page }) => {
    await mock(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/projects/${projectId}/sessions/new`);
    await expect(page.getByLabel('Message the agent')).toBeVisible();
    if (width > 760) {
      const rail = page.getByRole('complementary', { name: 'Project navigation', exact: true });
      await expect.poll(async () => (await rail.boundingBox())!.width).toBe(56);
      await expect(rail.getByRole('button', { name: 'Open account menu' })).toBeVisible();
      await expect(
        page.getByRole('complementary', { name: 'Worktrees', exact: true }),
      ).toBeVisible();
    } else {
      await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
      await expect(page.getByRole('dialog', { name: 'Navigation', exact: true })).toBeVisible();
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}

test('hosted run history keeps prior files and offers explicit resume after lost execution', async ({
  page,
}) => {
  await mock(page);
  await page.route('**/api/v1/agent-capabilities', (route) =>
    route.fulfill({
      json: {
        sessions: true,
        execution_available: false,
        hosted_agents: false,
        verification: false,
      },
    }),
  );
  await page.route('**/api/v1/agent-sessions/*/runs*', (route) =>
    route.fulfill({
      json: [
        {
          id: 'completed-run',
          status: 'COMPLETED',
          created_at: revision.created_at,
          failure_code: null,
        },
        {
          id: 'lost-run',
          status: 'FAILED',
          created_at: revision.created_at,
          failure_code: 'runner_lost_resume_required',
        },
      ],
    }),
  );
  await page.route('**/api/v1/agent-runs/completed-run/artifacts', (route) =>
    route.fulfill({ json: [{ artifact_id: 'saved-file', display_name: 'Saved result.txt' }] }),
  );
  await page.goto(`/projects/${projectId}/sessions/${sessionId}`);
  await expect(
    page.getByText('Review its history before resuming', { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Resume run' })).toBeDisabled();
  await page.getByRole('tab', { name: 'Agent history', exact: true }).click();
  await page.getByText('Files and run history', { exact: true }).click();
  await page.getByLabel('Files from completed run').selectOption('completed-run');
  await expect(page.getByRole('button', { name: 'Download Saved result.txt' })).toBeVisible();
  await expect(
    page.getByText('Your conversation and saved files remain accessible.', { exact: false }),
  ).toBeVisible();
});

test('signed-in nonmembers use the same project shell without member tools', async ({ page }) => {
  await mock(page, '');
  await page.goto('/projects?scope=public');
  await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
  await expect(page.locator('.project-grid .project-card')).toHaveCount(1);
  await page.getByRole('link', { name: 'Spectral gaps' }).click();
  await expect(page.getByRole('heading', { name: 'Spectral gaps', level: 1 })).toBeVisible();
  const navigation = page.getByRole('navigation', { name: 'Project sections' });
  await expect(navigation.getByRole('link', { name: 'Research objects' })).toBeVisible();
  await expect(navigation.getByRole('link', { name: 'Settings' })).toHaveCount(0);
  await expect(navigation.getByRole('link', { name: 'Proposal review' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Sign in to contribute' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'State a problem or claim' })).toHaveCount(0);
  await navigation.getByRole('link', { name: 'Research objects' }).click();
  await expect(
    page.getByRole('link', { name: `Open object: ${revision.title}`, exact: true }),
  ).toBeVisible();
  await expect(page.locator('#main')).toHaveCount(1);
});

test('public project search preserves scope and paginates server results', async ({ page }) => {
  await mock(page, '');
  const requests: Array<{ q: string | null; cursor: string | null }> = [];
  await page.route('**/api/v1/projects?*', async (route) => {
    const params = new URL(route.request().url()).searchParams;
    requests.push({ q: params.get('q'), cursor: params.get('cursor') });
    await route.fulfill({
      json: {
        items: Array.from({ length: params.has('cursor') ? 1 : 20 }, (_, index) => ({
          ...project,
          id: params.has('cursor') ? 'second-project' : `public-project-${index}`,
        })),
        total: 21,
        next_cursor: params.has('cursor') ? null : 'next-page',
      },
    });
  });
  await page.goto('/projects?scope=public');
  await page.getByLabel('Search', { exact: true }).fill('Spectral');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page).toHaveURL('/projects?scope=public&q=Spectral&sort=relevance');
  await expect.poll(() => requests.at(-1)?.q).toBe('Spectral');
  await expect(page.getByText('1-20 of 21 matches', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.locator('.project-card')).toHaveCount(1);
  await expect(page.getByText('Page 2', { exact: true })).toBeVisible();
  await expect(page.getByText('21-21 of 21 matches', { exact: true })).toBeVisible();
  expect(requests.at(-1)).toEqual({ q: 'Spectral', cursor: 'next-page' });
  await page.reload();
  await expect(page.getByLabel('Search', { exact: true })).toHaveValue('Spectral');
  await expect(page.locator('.project-card')).toHaveCount(20);
});

test('rail layout modes have stable panel headers and mobile navigation', async ({ page }) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/overview`);
  const rail = page.getByRole('complementary', { name: 'Project navigation', exact: true });
  for (const [label, name] of [
    ['Overview', 'Project'],
    ['Research objects', 'Research objects'],
    ['Map', 'Map'],
    ['Activity', 'Activity'],
  ]) {
    await rail.getByRole('link', { name: label, exact: true }).click();
    const panel = page.getByRole('complementary', { name: `${name} panel`, exact: true });
    await expect(panel.getByRole('heading', { name, exact: true, level: 2 })).toBeVisible();
    await expect(page.getByRole('tablist', { name: 'Project tabs' })).toHaveCount(0);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'Navigation', exact: true });
  await drawer.getByRole('link', { name: 'Overview', exact: true }).click();
  await expect(drawer).toHaveCount(0);
  await expect(page.getByRole('heading', { name: project.name, level: 1 })).toBeVisible();
});

test('icon rail stays fixed with reduced motion and has no collapse button', async ({ page }) => {
  await mock(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto(`/projects/${projectId}/overview`);
  const rail = page.getByRole('complementary', { name: 'Project navigation', exact: true });
  await rail.hover();
  await expect.poll(async () => (await rail.boundingBox())!.width).toBe(56);
  await expect(page.getByRole('button', { name: 'Collapse left sidebar' })).toHaveCount(0);
});

test('project keeps its rail and left panel fixed as the center grows', async ({ page }) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/map`);
  const rail = page.getByRole('complementary', { name: 'Project navigation', exact: true });
  const panel = page.getByRole('complementary', { name: 'Map panel', exact: true });
  for (const width of [1440, 1720, 1000]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(async () => (await rail.boundingBox())!.width).toBe(56);
    await expect
      .poll(async () => (await panel.boundingBox())!.width)
      .toBe(width <= 1050 ? 220 : 260);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  }
});

test('project tools collapse and restore their resized width', async ({ page }) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  const panel = page.getByRole('complementary', { name: 'Project tools', exact: true });
  await page.getByRole('separator', { name: 'Resize tools', exact: true }).press('ArrowLeft');
  const width = (await panel.boundingBox())!.width;
  await panel.getByRole('button', { name: 'Collapse tools' }).click();
  await expect(panel).toHaveCount(0);
  await page.getByRole('button', { name: 'Show tools', exact: true }).click();
  await expect.poll(async () => (await panel.boundingBox())!.width).toBe(width);
  await panel.getByRole('tab', { name: 'Details', exact: true }).click();
  await expect(panel.getByRole('tab', { name: 'Body', exact: true })).toBeVisible();
});

test('project activity scopes recent changes and paginates revision links', async ({ page }) => {
  await mock(page);
  const requests: URL[] = [];
  await page.route('**/api/v1/activity?**', async (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const more = url.searchParams.has('cursor');
    await route.fulfill({
      json: {
        items: [
          {
            id: more ? 'event-2' : 'event-1',
            submission_number: more ? 501 : 502,
            object_version_number: more ? 1 : 2,
            action: more ? 'object.created' : 'object.revised',
            actor: { kind: 'human', display_name: 'Ada' },
            title: more ? 'Original question' : 'Updated question',
            object_id: objectId,
            object_kind: 'PROBLEM',
            object_version_id: revisionId,
            project_id: projectId,
            occurred_at: new Date().toISOString(),
            excerpt_md: '',
            previous_object_version_id: null,
            contribution_id: null,
            reconstructed: false,
          },
        ],
        next_cursor: more ? null : 'next',
      },
    });
  });
  await page.goto(`/projects/${projectId}/map`);
  await page
    .getByRole('navigation', { name: 'Project sections' })
    .getByRole('link', { name: 'Activity', exact: true })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Activity', exact: true, level: 2 }),
  ).toBeVisible();
  const activityTitle = page.getByRole('button', {
    name: 'Inspect submission 502: Updated question',
    exact: true,
  });
  await activityTitle.focus();
  await page.keyboard.press('Enter');
  await expect(activityTitle).toBeFocused();
  await page.getByRole('button', { name: 'Load more activity' }).click();
  await expect(
    page.getByRole('region', { name: 'Project activity' }).locator('tbody tr'),
  ).toHaveCount(2);
  await expect(activityTitle).toHaveAttribute('aria-pressed', 'true');
  const panel = await projectInspector(page);
  await expect(panel).toContainText('Submission 502');
  await expect(panel).toContainText('Revised');
  await expect(panel.getByRole('link', { name: 'Open version v2' })).toHaveAttribute(
    'href',
    `/projects/${projectId}/records/${revisionId}`,
  );
  await page.screenshot({ path: '/tmp/polycolab-activity-table.png', fullPage: true });
  await panel.getByRole('button', { name: 'Clear submission selection' }).click();
  await expect(page.getByText('Select a change to see its details.')).toBeVisible();
  await expect(
    page.getByRole('complementary', { name: 'Activity details', exact: true }),
  ).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole('button', { name: 'Inspect submission 502: Updated question', exact: true })
    .click();
  await expect(page.getByRole('dialog', { name: 'Activity details', exact: true })).toContainText(
    'Submission 502',
  );
  await page.keyboard.press('Escape');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(
    requests.every(
      (url) =>
        url.searchParams.get('project_id') === projectId &&
        url.searchParams.get('scope') === 'member' &&
        url.searchParams.get('window') === 'month',
    ),
  ).toBe(true);
  expect(requests.some((url) => url.searchParams.get('cursor') === 'next')).toBe(true);
});

test('project overview centers the description without activity lists or requests', async ({
  page,
}) => {
  const requests = await mock(page);
  await page.goto(`/projects/${projectId}/overview`);
  const main = page.locator('#main');
  await expect(main.getByRole('heading', { name: 'Spectral gaps', exact: true })).toBeVisible();
  await expect(main.getByText(project.description, { exact: true })).toBeVisible();
  await expect(main.getByText('Project overview', { exact: true })).toHaveCount(0);
  await expect(main.getByText('Public', { exact: true })).toBeVisible();
  await expect(main.getByRole('button')).toHaveCount(0);
  await expect(main.getByRole('link')).toHaveCount(0);
  await expect(main.getByRole('list')).toHaveCount(0);
  await expect(main.getByRole('heading', { name: 'Recent changes' })).toHaveCount(0);
  expect(requests.some((path) => path.includes('/api/v1/activity'))).toBe(false);
  await page
    .getByRole('navigation', { name: 'Project sections' })
    .getByRole('link', { name: 'Research objects', exact: true })
    .click();
  await page.getByRole('button', { name: 'Create object', exact: true }).click();
  await page.getByLabel('Object type').selectOption('PROBLEM');
  await expect(
    page
      .getByRole('dialog', { name: 'Create object', exact: true })
      .getByLabel('Title', { exact: true }),
  ).toBeVisible();
});

test('project overview shows a quiet empty description', async ({ page }) => {
  await mock(page);
  await page.route(`**/api/v1/projects/${projectId}`, (route) =>
    route.fulfill({ json: { ...project, description: '' } }),
  );
  await page.goto(`/projects/${projectId}/overview`);
  const main = page.locator('#main');
  await expect(main.getByText('No project description yet.')).toBeVisible();
  await expect(main.getByRole('button')).toHaveCount(0);
  await expect(main.getByRole('link')).toHaveCount(0);
});

test('project remembers resized panels and collapsed tools after reload', async ({ page }) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/sessions/new`);
  await page.getByRole('separator', { name: 'Resize left panel', exact: true }).press('ArrowLeft');
  await page.getByRole('button', { name: 'Collapse tools', exact: true }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Show tools', exact: true })).toBeVisible();
  await expect(
    page.getByRole('separator', { name: 'Resize left panel', exact: true }),
  ).toHaveAttribute('aria-valuenow', '252');
});

test('dedicated objects share the body and relationship inspector', async ({ page }) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  const panel = await projectInspector(page);
  await expect(panel.getByRole('tab', { name: 'Body', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(panel.locator('.katex').first()).toBeVisible();
  await expect(panel).toContainText('v1');
  await panel.getByRole('tab', { name: /Relationships/ }).click();
  await expect(panel).toContainText('No relationships to show.');
});

test('focused object body renders Markdown and inline and display math with panel typography', async ({
  page,
}) => {
  await mock(page);
  await page.route(`**/api/v1/projects/${projectId}/objects**`, (route) =>
    route.fulfill({
      json: {
        items: [
          {
            ...object,
            current_object_version: {
              ...object.current_object_version,
              content: {
                ...object.current_object_version.content,
                content_md:
                  '# A bound\n\nA **strong** claim with $x^2$.\n\n- First premise\n- Second premise\n\n`exact`\n\n$$\nx^2 + y^2 = z^2\n$$',
              },
            },
          },
        ],
        next_cursor: null,
      },
    }),
  );
  await page.goto(`/projects/${projectId}/map`);
  await page
    .getByRole('list', { name: 'All objects', exact: true })
    .getByRole('button', { name: 'A spectral gap question', exact: true })
    .click();
  const body = page
    .locator('.project-tools .tool-content')
    .getByRole('tabpanel', { name: 'Body', exact: true });
  await expect(body.getByRole('heading', { name: 'A bound', exact: true })).toBeVisible();
  await expect(body.locator('strong')).toHaveText('strong');
  await expect(body.getByRole('listitem')).toHaveCount(2);
  await expect(body.locator('code')).toHaveText('exact');
  await expect(body.locator('.katex')).toHaveCount(2);
  await expect(body.locator('.katex-display')).toBeVisible();
  await expect(body.locator('.katex-error')).toHaveCount(0);
  await expect(body.locator('.prose')).toHaveCSS('font-size', '14px');
  await page.screenshot({ path: '/tmp/polycolab-focused-body.png', fullPage: true });
});

test('signed-out directory keeps both scopes and prompts for member projects', async ({ page }) => {
  await mock(page);
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json:
        new URL(route.request().url()).pathname === '/auth/config'
          ? { mode: 'local' }
          : { authenticated: false },
    }),
  );
  const memberRequests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname === '/api/v1/projects' && url.searchParams.get('scope') !== 'public')
      memberRequests.push(request.url());
  });
  await page.goto('/projects?scope=member');
  const scopes = page.getByRole('navigation', { name: 'Project scope' });
  await expect(scopes.getByRole('link', { name: 'Public', exact: true })).toBeVisible();
  await expect(scopes.getByRole('link', { name: 'Yours', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  const main = page.locator('#main');
  await expect(main).toContainText('to see your public and private projects.');
  await expect(main.getByRole('link', { name: 'Sign in', exact: true })).toHaveAttribute(
    'href',
    /returnTo=.*scope/,
  );
  await expect(main.getByRole('search')).toHaveCount(0);
  expect(memberRequests).toEqual([]);
  await scopes.getByRole('link', { name: 'Public', exact: true }).click();
  await expect(scopes.getByRole('link', { name: 'Public', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(main.getByRole('search')).toBeVisible();
});

test('member project directory searches all results and resets 20-card pages on filters', async ({
  page,
}) => {
  await mock(page);
  const requests: URL[] = [];
  await page.route('**/api/v1/projects?*', (route) => {
    const url = new URL(route.request().url());
    requests.push(url);
    const count = url.searchParams.has('q') ? 1 : url.searchParams.has('cursor') ? 2 : 20;
    return route.fulfill({
      json: {
        items: Array.from({ length: count }, (_, index) => ({
          ...project,
          id: `project-${url.searchParams.get('cursor') ?? 'first'}-${index}`,
          name: url.searchParams.has('q') ? 'Remote match' : `Project ${index}`,
        })),
        total: url.searchParams.has('q') ? 1 : 22,
        next_cursor: count === 20 ? 'next' : null,
      },
    });
  });
  await page.goto('/projects?scope=member');
  await expect(page.locator('.project-card')).toHaveCount(20);
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.locator('.project-card')).toHaveCount(2);
  await expect(page.getByText('21-22 of 22 projects', { exact: true })).toBeVisible();
  await expect(page.locator('.project-results-heading')).toBeFocused();
  await page.getByLabel('Search', { exact: true }).fill('remote');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Remote match', exact: true })).toBeVisible();
  expect(requests.at(-1)?.searchParams.get('q')).toBe('remote');
  expect(requests.at(-1)?.searchParams.has('cursor')).toBe(false);
  await page
    .getByRole('navigation', { name: 'Project categories' })
    .getByRole('button', { name: 'Shared', exact: true })
    .click();
  await expect.poll(() => requests.at(-1)?.searchParams.get('category')).toBe('shared');
  await page.getByLabel('Sort projects').selectOption('name');
  await expect.poll(() => requests.at(-1)?.searchParams.get('sort')).toBe('name');
  await page.getByLabel('Sort projects').selectOption('name_desc');
  await expect.poll(() => requests.at(-1)?.searchParams.get('sort')).toBe('name_desc');
  expect(requests.at(-1)?.searchParams.has('cursor')).toBe(false);
  expect(
    requests.every(
      (url) => url.searchParams.get('limit') === '20' && url.searchParams.get('scope') === 'member',
    ),
  ).toBe(true);
});

test('project sorting and pagination retain current cards while refreshing', async ({ page }) => {
  await mock(page);
  let release = () => {};
  let pending: Promise<void> | undefined;
  await page.route('**/api/v1/projects?*', async (route) => {
    const params = new URL(route.request().url()).searchParams;
    if (pending) await pending;
    const secondPage = params.has('cursor');
    await route.fulfill({
      json: {
        items: Array.from({ length: secondPage ? 2 : 20 }, (_, index) => ({
          ...project,
          id: `row-${secondPage ? 20 + index : index}`,
          name: `${params.get('sort') === 'name' ? 'Alphabetical' : 'Recent'} project ${secondPage ? 20 + index : index}`,
        })),
        total: 22,
        next_cursor: secondPage ? null : 'next',
      },
    });
  });
  await page.goto('/projects?scope=member');
  const results = page.getByRole('region', { name: 'Project results' });
  await expect(results.getByRole('article')).toHaveCount(20);
  pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  try {
    await page.getByLabel('Sort projects').selectOption('name');
    await expect(results).toHaveAttribute('aria-busy', 'true');
    await expect(page.getByRole('status')).toContainText('Updating');
    await expect(
      results.getByRole('link', { name: 'Recent project 0', exact: true }),
    ).toBeVisible();
    await expect(page.getByText('1-20 of 22 projects', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
  } finally {
    release();
  }
  await expect(
    results.getByRole('link', { name: 'Alphabetical project 0', exact: true }),
  ).toBeVisible();
  await expect(results).toHaveAttribute('aria-busy', 'false');
  pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  try {
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(results).toHaveAttribute('aria-busy', 'true');
    await expect(results.getByRole('article')).toHaveCount(20);
    await expect(page.getByText('1-20 of 22 projects', { exact: true })).toBeVisible();
  } finally {
    release();
  }
  await expect(results.getByRole('article')).toHaveCount(2);
  await expect(page.getByText('21-22 of 22 projects', { exact: true })).toBeVisible();
  await expect(results).toHaveAttribute('aria-busy', 'false');
});

test('project Agent connect provides scoped instructions and a collapsed navigation icon', async ({
  page,
}) => {
  await mock(page);
  await page.goto(`/projects/${projectId}`);
  const agentConnect = page
    .getByRole('complementary', { name: 'Project navigation', exact: true })
    .getByRole('link', { name: 'Agent connect', exact: true });
  await agentConnect.click();
  await expect(page).toHaveURL(`/projects/${projectId}/agent-connect`);
  await expect(page.getByRole('heading', { name: 'Agent connect', exact: true })).toBeVisible();
  const instructions = page.getByRole('textbox', { name: 'Agent connection instructions' });
  await expect(instructions).toHaveValue(new RegExp(`Project ID: ${projectId}`));
  await expect(instructions).toHaveValue(new RegExp(`${new URL(page.url()).origin}/SKILL.md`));
  await expect(instructions).toHaveValue(/Project name \(data\): "/);
  await expect(instructions).toHaveValue(
    /Do not inspect other private projects or save research until I give you a specific question/,
  );
  await expect(page.getByRole('button', { name: 'Create API key' })).toBeVisible();
  await page.getByRole('button', { name: 'Create API key' }).click();
  const keyDialog = page.getByRole('dialog', { name: 'Create API key' });
  await expect(keyDialog).toBeVisible();
  await expect(keyDialog).toContainText('every project you belong to');
  await keyDialog.getByLabel('Polycolab agent name').fill('Lean researcher');
  await keyDialog.getByLabel('Key name').fill('Lean helper');
  await keyDialog.getByRole('button', { name: 'Create API key' }).click();
  await expect(page.getByLabel('API key', { exact: true })).toHaveValue('shown-once-secret');
  await page.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page).toHaveURL(`/projects/${projectId}/agent-connect`);
  await expect(page.locator('#main')).toContainText('not limited to this project');
  const link = agentConnect;
  await expect(link).toHaveAttribute('aria-current', 'page');
  await link.hover();
  await expect(page.getByRole('tooltip')).toHaveText('Agent connect');
  await expect(link.locator('svg')).toBeVisible();
});

test('visitors can read Agent connect and sign in with the project guide as return path', async ({
  page,
}) => {
  await mock(page);
  await page.route('**/auth/**', (route) =>
    route.fulfill({
      json:
        new URL(route.request().url()).pathname === '/auth/config'
          ? { mode: 'local' }
          : { authenticated: false },
    }),
  );
  await page.goto(`/projects/${projectId}/agent-connect`);
  await expect(page.getByRole('heading', { name: 'Agent connect', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sign in to set up a key' })).toHaveAttribute(
    'href',
    `/signin?returnTo=%2Fprojects%2F${projectId}%2Fagent-connect`,
  );
  await expect(page.getByRole('textbox', { name: 'Agent connection instructions' })).toHaveValue(
    new RegExp(projectId),
  );
});

test('API keys table filters loaded rows and preserves cursor pagination', async ({
  page,
}, info) => {
  await mock(page);
  const base = {
    id: '01234567-89ab-4cde-8fab-0123456789ab',
    name: 'Research helper',
    agent_id: 'agent-a',
    project_id: null,
    scope_kind: 'ACCOUNT',
    sponsor_user_id: 'author-1',
    fixed_rights: [],
    created_at: '2026-01-01T00:00:00Z',
    expires_at: '2099-01-01T00:00:00Z',
    revoked_at: null,
    request_count: 20,
    mutation_count: 2,
    max_requests: 100,
    max_mutations: 20,
    allow_library_contributions: false,
  };
  await page.route('**/api/v1/account/agent-keys?*', (route) => {
    const more = new URL(route.request().url()).searchParams.get('cursor');
    return route.fulfill({
      json: more
        ? {
            items: [{ ...base, id: 'key-c', name: 'Later helper' }],
            next_cursor: null,
          }
        : {
            items: [
              base,
              { ...base, id: 'key-b', name: 'Old helper', revoked_at: '2026-02-01T00:00:00Z' },
            ],
            next_cursor: 'next-page',
          },
    });
  });
  await page.goto('/settings/api-keys');
  const table = page.getByRole('table', { name: 'Your API keys' });
  await expect(table.getByText('Research helper', { exact: true })).toBeVisible();
  await expect(table.getByRole('columnheader', { name: 'API key', exact: true })).toBeVisible();
  await expect(table.getByText('pca_01234567••••••••', { exact: true })).toBeVisible();
  await page.getByLabel('Search loaded API keys').fill('old');
  await expect(table.getByText('Research helper', { exact: true })).toHaveCount(0);
  await expect(table.getByText('Old helper', { exact: true })).toBeVisible();
  await page.getByLabel('Search loaded API keys').clear();
  await page.getByRole('button', { name: 'Filter keys by status' }).click();
  await page.getByRole('menuitemradio', { name: 'Active', exact: true }).click();
  await expect(table.getByText('Old helper', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Load more keys' }).click();
  await expect(table.getByText('Later helper', { exact: true })).toBeVisible();
  await expect(page.getByText('Showing 2 out of 3')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Load more keys' })).toHaveCount(0);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      width,
    );
    await page.screenshot({ path: info.outputPath(`api-keys-${width}.png`), fullPage: true });
  }
  await page.getByRole('button', { name: 'New API key' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.screenshot({ path: info.outputPath('api-key-dialog-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('focused object opens in the same tab without reloading the document', async ({
  page,
  context,
}) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/research`);
  await page
    .getByRole('table', { name: 'Research objects' })
    .getByRole('button', { name: revision.title, exact: true })
    .click();
  await page.evaluate(() => {
    document.documentElement.dataset.navigationMarker = 'retained';
  });
  const tabCount = context.pages().length;
  await page
    .locator('.project-tools .tool-content')
    .getByRole('link', { name: 'Open object', exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/objects/${objectId}$`));
  await expect(page.locator('html')).toHaveAttribute('data-navigation-marker', 'retained');
  expect(context.pages()).toHaveLength(tabCount);
});

test('object row open icon navigates without selecting the preview or opening a tab', async ({
  page,
  context,
}) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/research`);
  await page.evaluate(() => {
    document.documentElement.dataset.navigationMarker = 'retained';
  });
  const tabCount = context.pages().length;
  await page
    .getByRole('table', { name: 'Research objects' })
    .getByRole('link', { name: `Open object: ${revision.title}`, exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/objects/${objectId}$`));
  await expect(page.locator('html')).toHaveAttribute('data-navigation-marker', 'retained');
  expect(context.pages()).toHaveLength(tabCount);
});

test('dense map centers locally and fit all restores its overview', async ({ page }) => {
  await mock(page);
  await mockProjectGraph(page, 60, 59);
  await page.goto(`/projects/${projectId}/map`);
  const canvas = page.locator('[data-dense-graph] canvas');
  await expect(canvas).toBeVisible();
  await page.getByLabel('Focus on an object', { exact: true }).fill('"Statement 30"');
  await page
    .getByRole('list', { name: 'Focused object search results' })
    .getByRole('button', { name: 'Statement 30', exact: true })
    .click();
  await page.getByRole('button', { name: 'Fit all', exact: true }).click();
  const overview = await canvas.evaluate((element) => (element as HTMLCanvasElement).toDataURL());
  await page.getByRole('button', { name: 'Center focused object', exact: true }).click();
  await expect
    .poll(() => canvas.evaluate((element) => (element as HTMLCanvasElement).toDataURL()))
    .not.toBe(overview);
  await page.getByRole('button', { name: 'Fit all', exact: true }).click();
  await expect
    .poll(() => canvas.evaluate((element) => (element as HTMLCanvasElement).toDataURL()))
    .toBe(overview);
});

test('research object row focuses and centers the object on the map', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mock(page);
  await mockProjectGraph(page, 6, 5);
  await page.goto(`/projects/${projectId}/research`);
  await page.getByRole('link', { name: 'Focus on map: Statement 5', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/map\\?object=object-5$`));
  const graph = page.locator('.graph');
  const node = page.locator('.svelte-flow__node[data-id="version-5"]');
  await expect(
    page
      .getByRole('list', { name: 'All objects', exact: true })
      .getByRole('button', { name: 'Statement 5', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect
    .poll(async () => {
      const bounds = (await graph.boundingBox())!;
      const focused = (await node.boundingBox())!;
      return Math.abs(focused.x + focused.width / 2 - bounds.x - bounds.width / 2);
    })
    .toBeLessThan(3);
});

test('map review indicators show reviewer types without assessment outcomes', async ({ page }) => {
  await mock(page);
  const assessments = [
    {
      id: 'review-1',
      object_version_id: revisionId,
      reviewer_id: 'human:reviewer',
      actor_kind: 'HUMAN',
      reviewer_name: 'Reviewer',
      model_id: null,
      outcome: 'ISSUES_FOUND',
      scope: 'Boundary case',
      rationale: 'The empty case remains open.',
      evidence_object_version_ids: [],
      withdrawn: false,
      self_review: false,
      created_at: '2026-09-18T08:00:00Z',
    },
  ];
  let saved: Record<string, unknown> | undefined;
  await page.route('**/api/v1/reviews**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/summary')) {
      await route.fulfill({
        json: [
          {
            object_version_id: revisionId,
            human: { supports: 1, issues_found: 1, inconclusive: 0, self_reviews: 0 },
            ai: { supports: 0, issues_found: 0, inconclusive: 1, self_reviews: 0 },
            formal: 'UNAVAILABLE',
          },
        ],
      });
    } else if (route.request().method() === 'POST') {
      saved = route.request().postDataJSON();
      await route.fulfill({ status: 201, json: { replayed: false, outputs: [] } });
    } else {
      await route.fulfill({ json: { items: assessments, next_cursor: null } });
    }
  });
  await page.goto(`/projects/${projectId}/map`);
  await expect(page.getByText('Show supporting objects', { exact: true })).toHaveCount(0);
  const signal = page.getByRole('button', {
    name: 'Reviews for A spectral gap question',
    exact: true,
  });
  await expect(signal.getByLabel('Human reviewed', { exact: true })).toBeVisible();
  await expect(signal.getByLabel('AI reviewed', { exact: true })).toBeVisible();
  await expect(signal.getByLabel('Issues found', { exact: true })).toHaveCount(0);
  await expect(signal.getByLabel('Inconclusive', { exact: true })).toHaveCount(0);
  for (const label of ['Supports', 'Issues found', 'Inconclusive'])
    await expect(page.locator('.map-legend').getByText(label, { exact: true })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/polycolab-review-colors.png', fullPage: true });
  await signal.click();
  const panel = await projectInspector(page);
  await expect(panel.getByText('Reviewer', { exact: true })).toBeVisible();
  await panel
    .getByLabel('Comment (optional)', { exact: true })
    .fill('Checked the additional hypothesis.');
  await panel.getByRole('button', { name: 'Mark as reviewed', exact: true }).click();
  await expect.poll(() => saved?.object_version_id).toBe(revisionId);
  expect(saved?.outcome).toBe('REVIEWED');
  await expect(panel.getByText('The empty case remains open.', { exact: true })).toBeVisible();
  await expect(panel.getByRole('checkbox')).toHaveCount(0);
  await panel.getByRole('button', { name: 'Reviewed — review actions' }).click();
  await page.getByRole('menuitem', { name: 'Edit comment' }).click();
  await expect(panel.getByLabel('Comment (optional)', { exact: true })).toHaveValue(
    'Checked the additional hypothesis.',
  );
  await panel.getByLabel('Comment (optional)', { exact: true }).fill('Updated comment.');
  await panel.getByRole('button', { name: 'Save comment' }).click();
  await expect.poll(() => saved?.rationale).toBe('Updated comment.');
  await expect(panel.getByRole('button', { name: 'Reviewed — review actions' })).toBeEnabled();
  await page.screenshot({ path: '/tmp/polycolab-simple-reviews.png', fullPage: true });
  await panel.getByRole('button', { name: 'Reviewed — review actions' }).click();
  await page.getByRole('menuitem', { name: 'Remove review' }).click();
  await expect.poll(() => saved?.withdrawn).toBe(true);
  await expect(panel.getByRole('button', { name: 'Mark as reviewed' })).toBeVisible();
});

test('notes attempts and formalizations live in object tabs instead of map nodes', async ({
  page,
}) => {
  await mock(page);
  const contextObjects = ['NOTE', 'ATTEMPT', 'FORMALIZATION'].map((kind, index) => ({
    ...object,
    id: `context-${index}`,
    kind,
    current_object_version_id: `context-version-${index}`,
    current_object_version: {
      ...object.current_object_version,
      id: `context-version-${index}`,
      object_id: `context-${index}`,
      kind,
      content: {
        ...object.current_object_version.content,
        title: `${kind} context`,
        content_md: `Saved ${kind} body`,
        attached_object_ids: kind === 'FORMALIZATION' ? [] : [objectId],
      },
      structural_relationships:
        kind === 'ATTEMPT'
          ? [structuralPin('context-version-1', 'worked-on-old-version', 'TARGET')]
          : kind === 'FORMALIZATION'
            ? [structuralPin('context-version-2', revisionId)]
            : [],
    },
  }));
  await page.route(`**/api/v1/projects/${projectId}/objects**`, (route) =>
    route.fulfill({
      json: {
        items: [
          { ...object, current_object_version: { ...object.current_object_version, number: 2 } },
          ...contextObjects,
        ],
        next_cursor: null,
      },
    }),
  );
  await page.route('**/api/v1/objects/*/relations**', (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route('**/api/v1/reviews/summary**', (route) => route.fulfill({ json: [] }));
  await page.goto(`/projects/${projectId}/map`);
  await expect(page.locator('.svelte-flow__node')).toHaveCount(1);
  await expect(
    page.getByRole('region', { name: 'Map legend' }).getByText('Right panel', { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole('list', { name: 'All objects', exact: true })
    .getByRole('button', { name: 'A spectral gap question', exact: true })
    .click();
  const panel = await projectInspector(page);
  for (const [tab, kind] of [
    ['Notes', 'NOTE'],
    ['Attempts', 'ATTEMPT'],
    ['Formalizations', 'FORMALIZATION'],
  ]) {
    await panel.getByRole('tab', { name: new RegExp(`^${tab} 1$`) }).click();
    await panel.getByText(`${kind} context`, { exact: true }).click();
    await expect(
      panel.getByRole('tabpanel').getByText(`Saved ${kind} body`, { exact: true }).last(),
    ).toBeVisible();
    if (tab === 'Notes') {
      await expect(panel.getByRole('list', { name: 'Attached notes' })).toBeVisible();
      await expect(panel.getByRole('tabpanel').locator('details')).toHaveCount(0);
      await expect(panel.getByRole('link', { name: 'Open note', exact: true })).not.toHaveAttribute(
        'target',
        '_blank',
      );
      await page.screenshot({ path: '/tmp/polycolab-note-list.png', fullPage: true });
    }
  }
});

test('map draws statement proof and premises top down using simplified relationships', async ({
  page,
}) => {
  await mock(page);
  await mockProjectGraph(page, 3, 0, ['STATEMENT', 'PROOF', 'STATEMENT']);
  await page.route('**/api/v1/objects/*/relations**', (route) =>
    route.fulfill({
      json: {
        items: [
          structuralPin('version-1', 'version-0', 'CONCLUSION'),
          structuralPin('version-1', 'version-0'),
          structuralPin('version-1', 'version-2', 'PREMISE'),
        ],
        next_cursor: null,
      },
    }),
  );
  await page.goto(`/projects/${projectId}/map`);
  await expect(page.locator('.svelte-flow__node')).toHaveCount(3);
  await expect(page.locator('.svelte-flow__edge')).toHaveCount(2);
  const positions = await Promise.all(
    [0, 1, 2].map((index) =>
      page.locator(`.svelte-flow__node[data-id="version-${index}"]`).boundingBox(),
    ),
  );
  expect(positions[0]!.y).toBeLessThan(positions[1]!.y);
  expect(positions[1]!.y).toBeLessThan(positions[2]!.y);
  await page
    .getByRole('list', { name: 'All objects', exact: true })
    .getByRole('button', { name: 'Statement 0', exact: true })
    .click();
  const panel = await projectInspector(page);
  await panel.getByRole('tab', { name: /^Relationships/ }).click();
  await expect(panel.getByRole('heading', { name: 'Proved by (1)' })).toBeVisible();
  await expect(panel.getByRole('heading', { name: /Attachments/ })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/polycolab-top-down-relations.png', fullPage: true });
});

const mainWorktreeId = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';
function nativeTree(
  id: string,
  title: string,
  branch: string,
  savedRevision: string,
  files: Record<string, string>,
) {
  return {
    id,
    title,
    branch,
    project_id: projectId,
    created_by_user_id: author.id,
    created_at: revision.created_at,
    updated_at: revision.created_at,
    archived_at: null,
    head_commit: 'a'.repeat(40),
    revision: savedRevision,
    lifecycle: 'active',
    writable: true,
    changed_files: [],
    files: Object.entries(files).map(([path, value]) => ({
      path,
      size: value.length,
      executable: false,
    })),
  };
}
async function mockNativeFiles(
  page: Page,
  trees: () => ReturnType<typeof nativeTree>[],
  content: (id: string, path: string) => string,
  save?: (body: {
    expected_revision: string;
    changes: Array<{ path: string; content_base64: string }>;
  }) => string | undefined,
) {
  await page.route(`**/api/v1/projects/${projectId}/worktrees**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const id = url.pathname.split('/')[6];
    if (url.pathname.endsWith('/file'))
      return route.fulfill({
        json: {
          commit: url.searchParams.get('revision'),
          path: url.searchParams.get('path'),
          content_base64: Buffer.from(content(id!, url.searchParams.get('path')!)).toString(
            'base64',
          ),
        },
      });
    if (url.pathname.endsWith('/save') && save) {
      expect(request.headers()['idempotency-key']).toBeTruthy();
      const revision = save(request.postDataJSON());
      return revision
        ? route.fulfill({ json: { revision } })
        : route.fulfill({ status: 409, json: { error: { code: 'repository_stale_save' } } });
    }
    if (request.method() !== 'GET') return route.fallback();
    return route.fulfill({ json: id ? trees().find((tree) => tree.id === id) : trees() });
  });
}

test('project Files saves through the member API and retains stale drafts', async ({ page }) => {
  await mock(page);
  await page.route(`**/api/v1/projects/${projectId}/tasks*`, (route) =>
    route.fulfill({ json: [] }),
  );
  let head = 'a'.repeat(40);
  let saved = 'Initial note';
  let stale = false;
  await page.route(`**/api/v1/projects/${projectId}/repository**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/file'))
      return route.fulfill({
        json: {
          commit: head,
          path: 'notes.md',
          content_base64: Buffer.from(saved).toString('base64'),
        },
      });
    if (path.endsWith('/changes')) {
      if (stale)
        return route.fulfill({ status: 409, json: { error: { code: 'repository_stale_save' } } });
      const body = request.postDataJSON();
      expect(body.expected_commit).toBe(head);
      expect(request.headers()['idempotency-key']).toBeTruthy();
      saved = Buffer.from(body.changes[0].content_base64, 'base64').toString();
      head = 'b'.repeat(40);
      return route.fulfill({ json: { commit: head } });
    }
    return route.fulfill({
      json: {
        enabled: true,
        branch: 'main',
        commit: head,
        branches: { main: head },
        writable: true,
        files: [{ path: 'notes.md', size: saved.length, executable: false }],
      },
    });
  });
  await mockNativeFiles(
    page,
    () => [nativeTree(mainWorktreeId, 'Main', 'main', head, { 'notes.md': saved })],
    () => saved,
    (body) => {
      if (stale) return;
      expect(body.expected_revision).toBe(head);
      saved = Buffer.from(body.changes[0]!.content_base64, 'base64').toString();
      head = 'b'.repeat(40);
      return head;
    },
  );
  await page.goto(`/projects/${projectId}/files`);
  await page.getByRole('button', { name: 'notes.md', exact: true }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Initial note');
  await (await plainFileEditor(page)).fill('Updated note');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Saved.', { exact: true })).toBeVisible();
  expect(saved).toBe('Updated note');
  stale = true;
  await (await plainFileEditor(page)).fill('Draft to retain');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText(
    'Compare the latest version before saving again',
  );
  await expect(await plainFileEditor(page)).toHaveValue('Draft to retain');
});

test('Files workbench keeps tab drafts, explores folders, and reviews an agent copy on desktop and mobile', async ({
  page,
}) => {
  await mock(page);
  await page.route(`**/api/v1/projects/${projectId}/tasks*`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  const agentBranch = `sessions/${sessionId}`;
  const files: Record<string, string> = {
    'README.md':
      '# Spectral gaps\n\nResearch notes, proofs, and computational experiments.\n\n## Current direction\n\nExplore expansion in finite graphs and document the assumptions.\n\n- Work through the cycle graph example\n- Formalize the spectral gap bound\n- Compare numerical estimates with the proof\n',
    'notes/approach.md': '# Proof approach\n\nStart with the variational characterization.\n',
    'proofs/Main.lean':
      'import Mathlib\n\n-- Spectral gap investigation\n-- Record the hypotheses before the proof.\n',
    'experiments/gap.py':
      'import numpy as np\n\ndef spectral_gap(adjacency):\n    eigenvalues = np.linalg.eigvalsh(adjacency)\n    return eigenvalues[-1] - eigenvalues[-2]\n',
  };
  await page.route(`**/api/v1/projects/${projectId}/repository**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/file'))
      return route.fulfill({
        json: {
          commit: 'a'.repeat(40),
          path: url.searchParams.get('path'),
          content_base64: Buffer.from(files[url.searchParams.get('path')!]!).toString('base64'),
        },
      });
    if (url.pathname.endsWith('/history'))
      return route.fulfill({
        json: [
          {
            commit: 'a'.repeat(40),
            author: 'Ada',
            created_at: '2026-10-07T10:15:00Z',
            message: 'Save project files',
          },
        ],
      });
    if (url.pathname.endsWith('/diff'))
      return route.fulfill({
        json: 'diff --git a/notes/approach.md b/notes/approach.md\n@@ -1,2 +1,3 @@\n # Proof approach\n-Start with the variational characterization.\n+Use the normalized Laplacian.\n+State the connectedness assumption.',
      });
    if (url.pathname.endsWith('/merge'))
      return route.fulfill({
        json: {
          target_commit: 'a'.repeat(40),
          source_commit: 'b'.repeat(40),
          conflicts: [],
          diff: 'diff --git a/notes/approach.md b/notes/approach.md\n@@ -1,2 +1,3 @@\n # Proof approach\n-Start with the variational characterization.\n+Use the normalized Laplacian.\n+State the connectedness assumption.',
        },
      });
    const branch = url.searchParams.get('branch') || 'main';
    return route.fulfill({
      json: {
        enabled: true,
        writable: true,
        branch,
        commit: (branch === 'main' ? 'a' : 'b').repeat(40),
        branches: { main: 'a'.repeat(40), [agentBranch]: 'b'.repeat(40) },
        files: Object.entries(files).map(([path, value]) => ({
          path,
          size: value.length,
          executable: false,
        })),
      },
    });
  });
  await mockNativeFiles(
    page,
    () => [
      nativeTree(mainWorktreeId, 'Main', 'main', 'a'.repeat(40), files),
      nativeTree(sessionId, 'Agent worktree', agentBranch, 'b'.repeat(40), files),
    ],
    (_id, path) => files[path]!,
  );
  await page.goto(`/projects/${projectId}/files`);
  const navigator = page.getByRole('complementary', { name: 'Project tools', exact: true });
  await expect(navigator.getByLabel('Find a file')).toBeVisible();
  await expect(page.getByRole('main').getByLabel('Find a file')).toHaveCount(0);
  await expect(
    page.getByRole('main').getByRole('heading', { name: 'Files', exact: true }),
  ).toHaveCount(0);
  await expect
    .poll(() =>
      page.evaluate(() => {
        const center = document.querySelector('main')!.getBoundingClientRect();
        const navigator = document.querySelector('.project-tools')!.getBoundingClientRect();
        return navigator.x - center.right;
      }),
    )
    .toBeGreaterThanOrEqual(0);
  await navigator.getByRole('button', { name: 'README.md', exact: true }).click();
  await (await plainFileEditor(page)).fill('# My unsaved overview');
  await page.getByRole('button', { name: 'approach.md', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'approach.md', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await (await plainFileEditor(page)).fill('# My unsaved proof');
  await page.getByRole('tab', { name: 'README.md' }).click();
  await expect(await plainFileEditor(page)).toHaveValue('# My unsaved overview');
  await expect(page.getByText('2 unsaved files', { exact: true })).toBeVisible();
  // File state belongs to the project, not to the Files route.
  const projectNav = page.getByRole('navigation', { name: 'Project sections', exact: true });
  for (const section of ['Overview', 'Research objects', 'Activity']) {
    await projectNav.getByRole('link', { name: section, exact: true }).click();
    await expect(navigator).toHaveCount(0);
    await expect(page.getByRole('tab', { name: 'README.md' })).toHaveCount(0);
    await expect(page.getByRole('tab', { name: 'approach.md' })).toHaveCount(0);
  }
  await projectNav.getByRole('link', { name: 'Project', exact: true }).click();
  await expect(await plainFileEditor(page)).toHaveValue('# My unsaved overview');
  await page
    .getByRole('complementary', { name: 'Worktrees', exact: true })
    .getByRole('button', { name: 'New conversation in Main', exact: true })
    .click();
  await expect(page.getByLabel('Message the agent')).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-project-navigator-chat.png', fullPage: true });
  await navigator.getByRole('button', { name: 'README.md', exact: true }).click();
  await expect(await plainFileEditor(page)).toHaveValue('# My unsaved overview');
  await page.getByRole('tab', { name: 'New chat', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/sessions/new\\?draft=`));
  await page.getByRole('tab', { name: 'README.md' }).click();
  await expect(await plainFileEditor(page)).toHaveValue('# My unsaved overview');
  await expect(page.getByText('2 unsaved files', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Preview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'My unsaved overview' })).toBeVisible();
  await page.getByRole('button', { name: 'Source', exact: true }).click();
  await page.getByRole('button', { name: 'Main.lean', exact: true }).click();
  await page.getByLabel('Find a file').fill('approach');
  await expect(page.getByRole('button', { name: 'Main.lean', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'approach.md', exact: true })).toBeVisible();
  await page.getByLabel('Find a file').fill('');
  await page.screenshot({ path: '/tmp/polycolab-files-workbench-desktop.png', fullPage: true });
  await navigator.getByRole('tab', { name: 'Source control', exact: true }).click();
  await navigator.getByRole('button', { name: 'History & differences' }).click();
  await page.getByRole('button', { name: /Save project files/ }).click();
  await expect(page.getByRole('region', { name: 'File differences' })).toContainText(
    'State the connectedness assumption',
  );
  await page.getByRole('button', { name: 'Close history' }).click();
  await page.getByRole('separator', { name: 'Resize tools' }).press('ArrowLeft');
  await expect(page.getByRole('separator', { name: 'Resize tools' })).toHaveAttribute(
    'aria-valuenow',
    '288',
  );
  await page.getByRole('button', { name: 'Collapse tools', exact: true }).click();
  await expect(navigator).toHaveCount(0);
  await page.getByRole('tab', { name: 'README.md' }).click();
  await expect(await plainFileEditor(page)).toHaveValue('# My unsaved overview');
  await page.getByRole('button', { name: 'Show tools', exact: true }).click();
  await navigator.getByRole('tab', { name: 'Explorer', exact: true }).click();
  await expect(navigator.getByLabel('Find a file')).toBeVisible();
  await page.getByRole('button', { name: 'Select Agent worktree worktree' }).click();
  await expect(
    page.getByRole('button', { name: `Select ${'Agent worktree'} worktree`, exact: true }),
  ).toHaveAttribute('aria-current', 'true');
  await expect(page.getByRole('tab', { name: 'README.md' })).toHaveCount(0);
  await expect(page.getByRole('tab', { name: 'New chat', exact: true })).toHaveCount(0);
  await navigator.getByRole('tab', { name: 'Source control', exact: true }).click();
  await navigator.getByRole('button', { name: 'Merge into Main', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Merge review' })).toContainText(
    'State the connectedness assumption',
  );
  await page.screenshot({ path: '/tmp/polycolab-files-workbench-review.png', fullPage: true });
  await page.getByRole('button', { name: 'Close review' }).click();
  await navigator.getByRole('tab', { name: 'Explorer', exact: true }).click();
  await page.getByRole('button', { name: 'README.md', exact: true }).click();
  await page.getByRole('tab', { name: 'README.md', exact: true }).dblclick();
  await page.getByRole('tab', { name: 'Explorer', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Hide tools', exact: true }).click();
  const mobileNavigator = page.getByRole('dialog', { name: 'Project tools', exact: true });
  await mobileNavigator.getByRole('button', { name: 'approach.md', exact: true }).click();
  await expect(mobileNavigator).not.toBeVisible();
  await expect(page.getByRole('tab', { name: 'approach.md' })).toBeVisible();
  await page.getByRole('tab', { name: 'README.md' }).click();
  await page.getByRole('button', { name: 'Preview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Spectral gaps', exact: true })).toBeVisible();
  const dimensions = await page.evaluate(() => ({
    width: innerWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.width);
  await page.screenshot({ path: '/tmp/polycolab-files-workbench-mobile.png', fullPage: true });
});

test('agent workbench retains chat and file drafts across unified tabs and mobile drawers', async ({
  page,
}) => {
  const secondId = '66666666-6666-4666-8666-666666666666';
  const second = { ...session, id: secondId, title: 'Second investigation' };
  const requests = await mock(page, 'OWNER', 0, [session, second]);
  await page.route(`**/api/v1/projects/${projectId}/tasks*`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.route('**/api/v1/agent-sessions*', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/v1/agent-sessions')
      return route.fulfill({
        json: [
          { ...session, latest_run: { id: runId, status: 'RUNNING', cancel_requested_at: null } },
          second,
        ],
      });
    return route.fallback();
  });
  await page.route(`**/api/v1/agent-sessions/${secondId}`, (route) =>
    route.fulfill({ json: second }),
  );
  await page.route('**/api/v1/agent-sessions/*/runs*', (route) => route.fulfill({ json: [] }));
  await page.route(`**/api/v1/projects/${projectId}/repository**`, (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/file'))
      return route.fulfill({
        json: {
          commit: 'a'.repeat(40),
          path: 'notes.md',
          content_base64: Buffer.from('Saved note').toString('base64'),
        },
      });
    if (url.pathname.endsWith('/history'))
      return route.fulfill({
        json: [
          {
            commit: 'a'.repeat(40),
            author: 'Ada',
            created_at: revision.created_at,
            message: 'Saved notes',
          },
        ],
      });
    if (url.pathname.endsWith('/diff'))
      return route.fulfill({
        json: 'diff --git a/notes.md b/notes.md\n@@ -1 +1 @@\n-Saved note\n+Updated note',
      });
    return route.fulfill({
      json: {
        enabled: true,
        writable: true,
        branch: 'main',
        commit: 'a'.repeat(40),
        branches: { main: 'a'.repeat(40) },
        files: [{ path: 'notes.md', size: 10, executable: false }],
      },
    });
  });
  await mockNativeFiles(
    page,
    () => [
      nativeTree(mainWorktreeId, 'Main', 'main', 'a'.repeat(40), { 'notes.md': 'Saved note' }),
    ],
    () => 'Saved note',
  );
  await page.goto(`/projects/${projectId}`);
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/sessions/new$`));
  await expect(page.getByLabel('Message the agent').filter({ visible: true })).toBeVisible();
  const rail = page.getByRole('complementary', { name: 'Project navigation', exact: true });
  const agents = page.getByRole('complementary', { name: 'Worktrees', exact: true });
  const tools = page.getByRole('complementary', { name: 'Project tools', exact: true });
  await expect(agents).toBeVisible();
  await expect(tools).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-agent-workbench-desktop.png', fullPage: true });
  const centerX = (await page.getByRole('main').boundingBox())!.x;
  await expect(
    page
      .getByRole('complementary', { name: 'Worktrees', exact: true })
      .getByRole('link', { name: 'Polycolab projects', exact: true }),
  ).toHaveCount(0);
  expect((await page.getByRole('main').boundingBox())!.y).toBeLessThan(60);
  await rail.hover();
  await expect.poll(async () => (await rail.boundingBox())!.width).toBe(56);
  expect((await page.getByRole('main').boundingBox())!.x).toBe(centerX);
  const overviewIcon = rail.getByRole('link', { name: 'Project', exact: true });
  await overviewIcon.hover();
  await expect(page.getByRole('tooltip')).toHaveText('Project');
  await expect(overviewIcon).not.toHaveAttribute('title');
  const tooltipBox = (await page.getByRole('tooltip').boundingBox())!;
  const railBox = (await rail.boundingBox())!;
  expect(tooltipBox.x).toBeGreaterThanOrEqual(railBox.x + railBox.width);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await overviewIcon.focus();
  await expect(page.getByRole('tooltip')).toHaveText('Project');

  await expect.poll(async () => (await rail.boundingBox())!.width).toBe(56);
  await expect(rail.getByRole('button', { name: /Pin project navigation/ })).toHaveCount(0);
  expect((await page.getByRole('main').boundingBox())!.x).toBe(centerX);
  await page
    .getByLabel('Message the agent')
    .filter({ visible: true })
    .fill('Unsent new chat draft');
  await page
    .getByLabel('Message the agent')
    .filter({ visible: true })
    .fill('Discard this new chat draft');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Close New chat' }).click();
  await expect(page.getByText('Open a conversation or file to get started.')).toBeVisible();
  await page.getByRole('button', { name: 'New chat tab', exact: true }).click();
  await expect(page.getByLabel('Message the agent').filter({ visible: true })).toHaveValue('');
  await page
    .getByLabel('Message the agent')
    .filter({ visible: true })
    .fill('Unsent new chat draft');
  await agents.getByRole('button', { name: /Gap investigation Researcher running/ }).click();
  await expect(page).toHaveURL(new RegExp(`/sessions/${sessionId}$`));
  await page
    .getByLabel('Private message', { exact: true })
    .filter({ visible: true })
    .fill('First chat draft');
  await expect(
    page.getByLabel('Private message', { exact: true }).filter({ visible: true }),
  ).toHaveValue('First chat draft');
  await agents.getByRole('button', { name: /Second investigation Researcher/ }).click();
  await expect(page).toHaveURL(new RegExp(`/sessions/${secondId}$`));
  await expect(page.getByRole('tab', { name: /^Second investigation/ })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await page
    .getByLabel('Private message', { exact: true })
    .filter({ visible: true })
    .fill('Second chat draft');
  await tools.getByRole('button', { name: 'notes.md', exact: true }).click();
  await (await plainFileEditor(page)).fill('Unsent file draft');
  await page.getByRole('tab', { name: /^Gap investigation/ }).click();
  await expect(page).toHaveURL(new RegExp(`/sessions/${sessionId}$`));
  await expect(
    page.getByLabel('Private message', { exact: true }).filter({ visible: true }),
  ).toHaveValue('First chat draft');
  await page.getByRole('tab', { name: /^Second investigation/ }).click();
  await expect(page).toHaveURL(new RegExp(`/sessions/${secondId}$`));
  await expect(
    page.getByLabel('Private message', { exact: true }).filter({ visible: true }),
  ).toHaveValue('Second chat draft');
  await page.getByRole('tab', { name: /^New chat(?: Unsaved changes)?$/ }).click();
  await expect(page.getByLabel('Message the agent').filter({ visible: true })).toHaveValue(
    'Unsent new chat draft',
  );
  await page.getByRole('tab', { name: /notes.md/ }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Unsent file draft');
  await tools.getByRole('tab', { name: 'Agent history', exact: true }).click();
  await expect(tools.getByLabel('Find a file')).toHaveCount(0);
  await tools.getByRole('tab', { name: 'Source control', exact: true }).click();
  await tools.getByRole('button', { name: 'History & differences' }).click();
  await expect(page.getByRole('tab', { name: 'File history', exact: true })).toBeVisible();
  await page.getByRole('button', { name: /Saved notes/ }).click();
  await expect(page.getByRole('region', { name: 'File differences' })).toContainText(
    'Updated note',
  );
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Close Gap investigation' }).click();
  expect(requests.some((request) => request.includes('/cancel'))).toBe(false);
  await expect(
    agents.getByRole('button', { name: /Gap investigation Researcher running/ }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Navigation', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close drawer' }).click();
  await page.getByRole('button', { name: 'Hide left panel', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Worktrees', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Close drawer' }).click();
  await page.getByRole('button', { name: 'Hide tools', exact: true }).click();
  await page
    .getByRole('dialog', { name: 'Project tools', exact: true })
    .getByRole('tab', { name: 'Explorer', exact: true })
    .click();
  await expect(
    page.getByRole('dialog', { name: 'Project tools', exact: true }).getByLabel('Find a file'),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Close drawer' }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/polycolab-agent-workbench-mobile.png', fullPage: true });
});

test('retained chat tabs pause streams and resume with their cursor and draft', async ({
  page,
}) => {
  const chats = Array.from({ length: 8 }, (_, index) => ({
    ...session,
    id: `44444444-4444-4444-8444-${String(index + 1).padStart(12, '0')}`,
    title: `Stream investigation ${index + 1}`,
  }));
  const requests = await mock(page, 'OWNER', 0, chats);
  await page.route('**/api/v1/agent-sessions/*', (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1);
    return route.fulfill({ json: chats.find((chat) => chat.id === id) });
  });
  await page.route('**/api/v1/agent-sessions/*/runs*', (route) => route.fulfill({ json: [] }));
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    const monitor = { active: 0, maximum: 0, aborted: 0, cursors: [] as string[] };
    Object.assign(window, { chatStreamMonitor: monitor });
    window.fetch = async (input, init) => {
      const request = new Request(input, init);
      if (!/\/agent-sessions\/[^/]+\/events$/.test(new URL(request.url).pathname))
        return originalFetch(input, init);
      monitor.active++;
      monitor.maximum = Math.max(monitor.maximum, monitor.active);
      const cursor = request.headers.get('Last-Event-ID') || '';
      monitor.cursors.push(cursor);
      let finished = false;
      const finish = () => {
        if (!finished) {
          finished = true;
          monitor.active--;
        }
      };
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          if (!cursor)
            controller.enqueue(
              new TextEncoder().encode(
                'id: 1:1\nevent: ASSISTANT_DELTA\ndata: {"kind":"ASSISTANT_DELTA","payload":{"text":"Live text"}}\n\n',
              ),
            );
          request.signal.addEventListener(
            'abort',
            () => {
              monitor.aborted++;
              finish();
              controller.error(new DOMException('Aborted', 'AbortError'));
            },
            { once: true },
          );
        },
        cancel: finish,
      });
      return new Response(body, { headers: { 'Content-Type': 'text/event-stream' } });
    };
  });
  const monitor = () =>
    page.evaluate(
      () =>
        (
          window as typeof window & {
            chatStreamMonitor: {
              active: number;
              maximum: number;
              aborted: number;
              cursors: string[];
            };
          }
        ).chatStreamMonitor,
    );
  await page.goto(`/projects/${projectId}/sessions/${chats[0]!.id}`);
  const agents = page.getByRole('complementary', { name: 'Worktrees', exact: true });
  await expect.poll(async () => (await monitor()).active).toBe(1);
  await page
    .getByLabel('Private message', { exact: true })
    .filter({ visible: true })
    .fill('Keep this draft');
  for (const chat of chats.slice(1)) {
    await agents.getByRole('button', { name: new RegExp(chat.title) }).click();
    await expect(page).toHaveURL(new RegExp(`/sessions/${chat.id}$`));
    await expect.poll(async () => (await monitor()).active).toBe(1);
  }
  await expect.poll(async () => (await monitor()).aborted).toBeGreaterThanOrEqual(7);
  expect((await monitor()).maximum).toBe(1);
  const beforeRefresh = requests.filter((request) =>
    request.endsWith(`/${chats[0]!.id}/messages`),
  ).length;
  await page.getByRole('tab', { name: /^Stream investigation 1(?: Unsaved changes)?$/ }).click();
  await expect(
    page.getByLabel('Private message', { exact: true }).filter({ visible: true }),
  ).toHaveValue('Keep this draft');
  await expect.poll(async () => (await monitor()).cursors.at(-1)).toBe('1:1');
  await expect
    .poll(() => requests.filter((request) => request.endsWith(`/${chats[0]!.id}/messages`)).length)
    .toBeGreaterThan(beforeRefresh);
  await page
    .getByRole('complementary', { name: 'Project navigation', exact: true })
    .getByRole('link', { name: 'Research objects', exact: true })
    .click();
  await expect.poll(async () => (await monitor()).active).toBe(0);
});

test('middle panel plus creates independent new chat tabs and preserves their drafts', async ({
  page,
}) => {
  const requests = await mock(page);
  await page.route(`**/api/v1/agent-sessions/${sessionId}/messages`, (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ json: { id: runId, session_id: sessionId, status: 'QUEUED' } })
      : route.fallback(),
  );
  await page.goto(`/projects/${projectId}/sessions/new`);
  const tabs = page.getByRole('tab', { name: /^New chat(?: Unsaved changes)?$/ });
  const composer = page.getByLabel('Message the agent').filter({ visible: true });
  const plus = page.getByRole('button', { name: 'New chat tab', exact: true });
  await composer.fill('First draft');
  await plus.click();
  await expect(tabs).toHaveCount(2);
  await expect(composer).toHaveValue('');
  await expect(page).toHaveURL(new RegExp('/sessions/new\\?draft='));
  const secondUrl = page.url();
  await composer.fill('Second draft');
  await plus.click();
  await expect(tabs).toHaveCount(3);
  await expect(composer).toHaveValue('');
  await expect(page).not.toHaveURL(secondUrl);
  await composer.fill('Third draft');
  expect(requests.filter((request) => request === 'POST /api/v1/agent-sessions')).toHaveLength(0);

  await tabs.nth(0).click();
  await expect(composer).toHaveValue('First draft');
  await tabs.nth(1).click();
  await expect(composer).toHaveValue('Second draft');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Close New chat', exact: true }).nth(1).click();
  await expect(tabs).toHaveCount(3);
  await expect(composer).toHaveValue('Second draft');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Close New chat', exact: true }).nth(1).click();
  await expect(tabs).toHaveCount(2);
  await expect(composer).toHaveValue('Third draft');

  await tabs.nth(0).click();
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/sessions/${sessionId}$`));
  await expect(tabs).toHaveCount(1);
  await tabs.click();
  await expect(composer).toHaveValue('Third draft');
  await plus.click();
  await expect(tabs).toHaveCount(2);
  await expect(composer).toHaveValue('');
});

const workbenchTaskId = '77777777-7777-4777-8777-777777777777';
const otherWorkbenchTaskId = '88888888-8888-4888-8888-888888888888';
function workbenchTask(id: string, title: string) {
  return {
    id,
    project_id: projectId,
    title,
    branch: `tasks/${id}`,
    created_by_user_id: 'author-1',
    created_at: revision.created_at,
    updated_at: revision.created_at,
    archived_at: null as string | null,
  };
}
async function mockTaskWorkbench(page: Page) {
  const secondChatId = '99999999-9999-4999-8999-999999999999';
  const chats: Array<typeof session & { task_id: string | null }> = [
    { ...session, task_id: workbenchTaskId },
    { ...session, id: secondChatId, title: 'Second proof conversation', task_id: workbenchTaskId },
  ];
  await mock(page, 'OWNER', 0, chats);
  const tasks = [
    workbenchTask(workbenchTaskId, 'Prove the spectral bound'),
    workbenchTask(otherWorkbenchTaskId, 'Check numerical examples'),
  ];
  const writes: Array<{ method: string; body: Record<string, unknown> }> = [];
  let sessionCreate: Record<string, unknown> | undefined;
  await page.route(`**/api/v1/projects/${projectId}/worktrees**`, (route) => {
    const request = route.request();
    const id = new URL(request.url()).pathname.split('/')[6];
    if (request.method() === 'POST') {
      const body = request.postDataJSON();
      writes.push({ method: 'POST', body });
      const created = { ...workbenchTask(body.client_request_id, body.title), branch: body.branch };
      if (!tasks.some((task) => task.id === created.id)) tasks.push(created);
      return route.fulfill({ json: tasks.find((task) => task.id === created.id) });
    }
    if (request.method() === 'PATCH') {
      const body = request.postDataJSON();
      writes.push({ method: 'PATCH', body });
      const index = tasks.findIndex((task) => task.id === id);
      if (index < 0) return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } });
      tasks[index] = {
        ...tasks[index]!,
        ...(body.title ? { title: body.title } : {}),
        ...(typeof body.archived === 'boolean'
          ? { archived_at: body.archived ? revision.created_at : null }
          : {}),
      };
      return route.fulfill({ json: tasks[index] });
    }
    return route.fulfill({ json: id ? tasks.find((task) => task.id === id) : tasks });
  });
  await page.route('**/api/v1/agent-sessions', (route) => {
    if (route.request().method() === 'POST') {
      sessionCreate = route.request().postDataJSON();
      const created = {
        ...session,
        id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        title: 'New conversation',
        task_id: sessionCreate!.worktree_id as string,
      };
      chats.push(created);
      return route.fulfill({ json: created });
    }
    return route.fulfill({ json: chats });
  });
  await page.route('**/api/v1/agent-sessions/*', (route) => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1);
    const chat = chats.find((item) => item.id === id);
    return chat ? route.fulfill({ json: chat }) : route.fallback();
  });
  await page.route('**/api/v1/agent-sessions/*/runs*', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/v1/agent-sessions/*/messages', (route) =>
    route.fulfill({
      json:
        route.request().method() === 'POST'
          ? { id: runId, session_id: chats.at(-1)!.id, status: 'QUEUED' }
          : [],
    }),
  );
  await page.route(`**/api/v1/projects/${projectId}/repository**`, (route) => {
    const url = new URL(route.request().url());
    const commitFor = (branch: string) =>
      (branch === 'main' ? 'a' : branch.endsWith(workbenchTaskId) ? 'b' : 'c').repeat(40);
    const requestedCommit = url.searchParams.get('commit');
    const branch =
      url.searchParams.get('branch') ||
      tasks.find((task) => commitFor(task.branch) === requestedCommit)?.branch ||
      'main';
    if (url.pathname.endsWith('/file'))
      return route.fulfill({
        json: {
          commit: commitFor(branch),
          path: 'notes.md',
          content_base64: Buffer.from(`Saved files in ${branch}`).toString('base64'),
        },
      });
    return route.fulfill({
      json: {
        enabled: true,
        writable: true,
        branch,
        commit: commitFor(branch),
        branches: Object.fromEntries([
          ['main', 'a'.repeat(40)],
          ...tasks.map((task) => [task.branch, commitFor(task.branch)]),
        ]),
        files: [{ path: 'notes.md', size: 20, executable: false }],
      },
    });
  });
  const commitFor = (branch: string) =>
    (branch === 'main' ? 'a' : branch.endsWith(workbenchTaskId) ? 'b' : 'c').repeat(40);
  await mockNativeFiles(
    page,
    () => [
      nativeTree(mainWorktreeId, 'Main', 'main', 'a'.repeat(40), {
        'notes.md': 'Saved files in main',
      }),
      ...tasks.map((task) =>
        nativeTree(task.id, task.title, task.branch, commitFor(task.branch), {
          'notes.md': `Saved files in ${task.branch}`,
        }),
      ),
    ],
    (id) => `Saved files in ${tasks.find((task) => task.id === id)?.branch || 'main'}`,
  );
  return { tasks, chats, writes, sessionCreate: () => sessionCreate };
}

test('worktrees group conversations and switch saved files on desktop and mobile', async ({
  page,
}) => {
  const fixture = await mockTaskWorkbench(page);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/projects/${projectId}`);
  const panel = page.getByRole('complementary', { name: 'Worktrees', exact: true });
  const tools = page.getByRole('complementary', { name: 'Project tools', exact: true });
  await expect(
    panel.getByRole('button', { name: 'Select Main worktree', exact: true }),
  ).toBeVisible();
  await expect(panel.getByRole('textbox')).toHaveCount(0);
  await expect(panel.getByText('Shared project')).toHaveCount(0);
  await panel
    .getByRole('button', { name: 'Select Prove the spectral bound worktree', exact: true })
    .click();
  await expect(
    page.getByRole('button', {
      name: `Select ${'Prove the spectral bound'} worktree`,
      exact: true,
    }),
  ).toHaveAttribute('aria-current', 'true');
  const group = panel.getByRole('region', { name: 'Prove the spectral bound worktree' });
  await expect(group.getByRole('button', { name: /Gap investigation Researcher/ })).toBeVisible();
  await expect(
    group.getByRole('button', { name: /Second proof conversation Researcher/ }),
  ).toBeVisible();
  await group.getByRole('button', { name: /Gap investigation Researcher/ }).click();
  await expect(page).toHaveURL(new RegExp(`/sessions/${sessionId}$`));
  await tools.getByRole('button', { name: 'notes.md', exact: true }).click();
  await expect(await plainFileEditor(page)).toHaveValue(`Saved files in tasks/${workbenchTaskId}`);
  await (await plainFileEditor(page)).fill('Keep this worktree draft');
  await panel.getByRole('button', { name: 'Select Main worktree', exact: true }).click();
  await expect(
    page.getByRole('button', { name: `Select ${'Main'} worktree`, exact: true }),
  ).toHaveAttribute('aria-current', 'true');
  await panel.getByRole('button', { name: 'Select Prove the spectral bound worktree' }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Keep this worktree draft');
  await panel.getByRole('button', { name: 'Select Main worktree', exact: true }).click();
  await expect(
    page.getByRole('button', { name: `Select ${'Main'} worktree`, exact: true }),
  ).toHaveAttribute('aria-current', 'true');
  await panel.getByRole('button', { name: 'New worktree', exact: true }).click();
  await panel.getByLabel('Worktree name', { exact: true }).fill('Alternate proof');
  await panel.getByRole('button', { name: 'Create worktree', exact: true }).click();
  await expect(
    panel.getByRole('button', { name: 'Select Alternate proof worktree' }),
  ).toHaveAttribute('aria-current', 'true');
  const created = fixture.tasks.find((item) => item.title === 'Alternate proof')!;
  await expect(
    page.getByRole('button', { name: `Select ${created.title} worktree`, exact: true }),
  ).toHaveAttribute('aria-current', 'true');
  await panel
    .getByRole('button', { name: 'New conversation in Alternate proof', exact: true })
    .click();
  await expect(page).toHaveURL(new RegExp(`worktree=${created.id}`));
  await page
    .getByLabel('Message the agent')
    .filter({ visible: true })
    .fill('Explore an alternate proof');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect.poll(() => fixture.sessionCreate()?.worktree_id).toBe(created.id);
  await expect(page).toHaveURL(/sessions\/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa$/);
  await page.reload();
  await expect(
    panel
      .getByRole('region', { name: 'Alternate proof worktree' })
      .getByRole('button', { name: /New conversation Researcher/ }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'New chat tab', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`worktree=${created.id}`));
  await page
    .getByLabel('Message the agent')
    .filter({ visible: true })
    .fill('Keep this worktree chat draft');
  await panel.getByRole('button', { name: 'New conversation in Main', exact: true }).click();
  await expect(page).toHaveURL(/sessions\/new\?draft=/);
  expect(new URL(page.url()).searchParams.get('worktree')).toBe(mainWorktreeId);
  await panel.getByRole('button', { name: 'Select Alternate proof worktree' }).click();
  await expect(
    page.getByRole('button', { name: `Select ${created.title} worktree`, exact: true }),
  ).toHaveAttribute('aria-current', 'true');
  await page.getByRole('tab', { name: /^New chat Unsaved changes$/ }).click();
  await expect(page.getByLabel('Message the agent').filter({ visible: true })).toHaveValue(
    'Keep this worktree chat draft',
  );
  await expect(
    page.getByRole('button', { name: `Select ${created.title} worktree`, exact: true }),
  ).toHaveAttribute('aria-current', 'true');
  await page.screenshot({ path: '/tmp/polycolab-worktrees-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Hide left panel', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'Worktrees', exact: true });
  await drawer
    .getByRole('button', { name: 'Toggle Prove the spectral bound conversations' })
    .click();
  await expect(
    drawer.getByRole('button', { name: /Second proof conversation Researcher/ }),
  ).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-worktrees-mobile.png', fullPage: true });
  await drawer.getByRole('button', { name: /Second proof conversation Researcher/ }).click();
  await expect(page).toHaveURL(new RegExp(`/sessions/${fixture.chats[1]!.id}$`));
  await expect(drawer).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('conversation navigation ignores a delayed legacy working-copy response', async ({ page }) => {
  const fixture = await mockTaskWorkbench(page);
  const sharedId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  fixture.chats.push({ ...session, id: sharedId, title: 'Shared conversation', task_id: null });
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let pending = false;
  await page.route(`**/api/v1/projects/${projectId}/repository?**`, async (route) => {
    if (new URL(route.request().url()).searchParams.get('branch') === `tasks/${workbenchTaskId}`) {
      pending = true;
      await gate;
    }
    await route.fallback();
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/projects/${projectId}`);
  const panel = page.getByRole('complementary', { name: 'Worktrees', exact: true });
  const tools = page.getByRole('complementary', { name: 'Project tools', exact: true });
  await panel
    .getByRole('button', { name: 'Toggle Prove the spectral bound conversations' })
    .click();
  await panel.getByRole('button', { name: /Gap investigation Researcher/ }).click();
  await expect.poll(() => pending).toBe(true);
  await panel.getByRole('button', { name: /Shared conversation Researcher/ }).click();
  release();
  await expect(page).toHaveURL(new RegExp(`/sessions/${sharedId}$`));
  await expect(page.getByRole('tab', { name: 'Shared conversation', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(
    page.getByRole('button', { name: `Select ${'Main'} worktree`, exact: true }),
  ).toHaveAttribute('aria-current', 'true');
  await expect(
    panel.getByRole('button', { name: /Shared conversation Researcher/ }),
  ).toHaveAttribute('aria-current', 'true');
  await tools.getByRole('button', { name: 'notes.md', exact: true }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Saved files in main');
  expect(errors).toEqual([]);
});

test('project rail switches page layouts without adding tabs and restores chat drafts', async ({
  page,
}) => {
  await mock(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/projects/${projectId}/sessions/new`);
  const rail = page.getByRole('complementary', { name: 'Project navigation', exact: true });
  const composer = page.getByLabel('Message the agent').filter({ visible: true });
  await composer.fill('Keep this layout-switch draft');
  await expect(page.getByRole('tab', { name: /^New chat/ })).toHaveCount(1);
  const projectWidth = (await page.getByRole('main').boundingBox())!.width;
  for (const [label, panel] of [
    ['Overview', 'Project panel'],
    ['Research objects', 'Research objects panel'],
    ['Activity', 'Activity panel'],
    ['Map', 'Map panel'],
  ]) {
    await rail.getByRole('link', { name: label, exact: true }).click();
    await expect(page.getByRole('complementary', { name: panel, exact: true })).toBeVisible();
    await expect(page.getByRole('complementary', { name: 'Worktrees', exact: true })).toHaveCount(
      0,
    );
    await expect(
      page.getByRole('complementary', { name: 'Project tools', exact: true }),
    ).toHaveCount(0);
    await expect(page.getByRole('tab', { name: /^New chat/ })).toHaveCount(0);
    expect((await page.getByRole('main').boundingBox())!.width).toBeGreaterThan(projectWidth);
    if (label === 'Overview') await page.screenshot({ path: '/tmp/polycolab-project-layout.png' });
  }
  await page.goBack();
  await expect(
    page.getByRole('complementary', { name: 'Activity panel', exact: true }),
  ).toBeVisible();
  await page.goForward();
  await expect(page.getByRole('complementary', { name: 'Map panel', exact: true })).toBeVisible();
  await rail.getByRole('link', { name: 'Project', exact: true }).click();
  await expect(composer).toHaveValue('Keep this layout-switch draft');
  await expect(page.getByRole('tab', { name: /^New chat/ })).toHaveCount(1);
  await expect(page.getByRole('complementary', { name: 'Worktrees', exact: true })).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-project-layout.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  const drawer = page.getByRole('dialog');
  await drawer.getByRole('link', { name: 'Overview', exact: true }).click();
  await expect(page.getByRole('heading', { name: project.name, exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Hide left panel', exact: true }).click();
  await expect(
    page.getByRole('dialog').getByRole('navigation', { name: 'Project pages' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Close drawer' }).click();
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  await page.getByRole('dialog').getByRole('link', { name: 'Project', exact: true }).click();
  await expect(composer).toHaveValue('Keep this layout-switch draft');
});

test('closing the last tab leaves an empty workbench and retains its worktree', async ({
  page,
}) => {
  await mockTaskWorkbench(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/projects/${projectId}/sessions/new?draft=last&worktree=${workbenchTaskId}`);
  const tabStrip = page.getByRole('tablist', { name: 'Project tabs' });
  const tools = page.getByRole('complementary', { name: 'Project tools', exact: true });
  const empty = page.getByText('Open a conversation or file to get started.', { exact: true });
  const composer = page.getByLabel('Message the agent').filter({ visible: true });
  await composer.fill('Keep until confirmed');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Close New chat', exact: true }).click();
  await expect(composer).toHaveValue('Keep until confirmed');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Close New chat', exact: true }).click();
  await expect(empty).toBeVisible();
  await expect(tabStrip.getByRole('tab')).toHaveCount(0);
  await expect(page).toHaveURL(/sessions\?view=empty/);
  await expect(
    page.getByRole('button', {
      name: `Select ${'Prove the spectral bound'} worktree`,
      exact: true,
    }),
  ).toHaveAttribute('aria-current', 'true');
  await page.reload();
  await expect(empty).toBeVisible();
  await expect(tabStrip.getByRole('tab')).toHaveCount(0);
  await expect(
    page.getByRole('button', {
      name: `Select ${'Prove the spectral bound'} worktree`,
      exact: true,
    }),
  ).toHaveAttribute('aria-current', 'true');
  const rail = page.getByRole('complementary', { name: 'Project navigation', exact: true });
  await rail.getByRole('link', { name: 'Overview', exact: true }).click();
  await rail.getByRole('link', { name: 'Project', exact: true }).click();
  await expect(empty).toBeVisible();
  await expect(tabStrip.getByRole('tab')).toHaveCount(0);
  await tools.getByRole('button', { name: 'notes.md', exact: true }).click();
  await expect(await plainFileEditor(page)).toBeVisible();
  await (await plainFileEditor(page)).fill('Unsaved file');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: 'Close notes.md', exact: true }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Unsaved file');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Close notes.md', exact: true }).click();
  await expect(empty).toBeVisible();
  await expect(tabStrip.getByRole('tab')).toHaveCount(0);
  await page.getByRole('button', { name: 'New chat tab', exact: true }).click();
  await expect(composer).toHaveValue('');
  await expect(page).toHaveURL(new RegExp(`worktree=${workbenchTaskId}`));
  await expect(tabStrip.getByRole('tab')).toHaveCount(1);
});

test('Explorer previews retain edited Monaco models and isolate the same path across worktrees', async ({
  page,
}) => {
  await mockTaskWorkbench(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/projects/${projectId}/sessions?view=empty&branch=main`);
  const tools = page.getByRole('complementary', { name: 'Project tools', exact: true });
  const tabs = page.getByRole('tablist', { name: 'Project tabs' });
  await tools.getByRole('button', { name: 'notes.md', exact: true }).click();
  const editor = page.locator('.monaco-source-editor .monaco-editor');
  await expect(editor).toBeVisible();
  const preview = tabs.getByRole('tab', { name: /^notes\.md(?: Unsaved changes)?$/ });
  await expect(preview.locator('span').first()).toHaveCSS('font-style', 'italic');
  await editor.locator('.view-lines').click();
  await page.keyboard.press('ControlOrMeta+End');
  await page.keyboard.press('Enter');
  await page.keyboard.type('main-only draft');
  await expect(preview.locator('span').first()).toHaveCSS('font-style', 'normal');
  await expect(editor.locator('.view-lines')).toContainText('main-only draft');
  await page
    .getByRole('button', { name: 'Select Prove the spectral bound worktree', exact: true })
    .click();
  await tools.getByRole('button', { name: 'notes.md', exact: true }).click();
  await expect(editor.locator('.view-lines')).not.toContainText('main-only draft');
  await page.getByRole('button', { name: 'Select Main worktree', exact: true }).click();
  await expect(editor.locator('.view-lines')).toContainText('main-only draft');
  await editor.locator('.view-lines').click();
  await page.keyboard.press('ControlOrMeta+z');
  await expect(editor.locator('.view-lines')).not.toContainText('main-only draft');
});

test('Explorer preview replacement, explicit filter reveal, and clean failure preserve the selected file', async ({
  page,
}) => {
  await mockTaskWorkbench(page);
  const contents = {
    'src/a.py': 'a = 1',
    'src/b.py': 'b = 2',
    '.config.json': '{}',
    'broken.py': '',
  };
  await mockNativeFiles(
    page,
    () => [nativeTree(mainWorktreeId, 'Main', 'main', 'a'.repeat(40), contents)],
    (_id, path) => contents[path as keyof typeof contents],
  );
  await page.route(`**/worktrees/${mainWorktreeId}/file?**`, (route) =>
    new URL(route.request().url()).searchParams.get('path') === 'broken.py'
      ? route.fulfill({ status: 503, json: { error: { code: 'unavailable' } } })
      : route.fallback(),
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/projects/${projectId}/sessions?view=empty&branch=main`);
  const tools = page.getByRole('complementary', { name: 'Project tools', exact: true });
  const tabs = page.getByRole('tablist', { name: 'Project tabs' });
  await tools.getByRole('button', { name: 'a.py', exact: true }).click();
  await expect(tabs.getByRole('tab', { name: 'a.py', exact: true })).toBeVisible();
  await tools.getByRole('button', { name: 'b.py', exact: true }).click();
  await expect(tabs.getByRole('tab', { name: 'a.py', exact: true })).toHaveCount(0);
  await tabs.getByRole('tab', { name: 'b.py', exact: true }).dblclick();
  await tools.getByRole('button', { name: 'a.py', exact: true }).click();
  await tools.getByLabel('Find a file').fill('b.py');
  await expect(tools.getByRole('button', { name: 'a.py', exact: true })).toHaveCount(0);
  await tools.getByRole('button', { name: 'Reveal active file' }).click();
  await expect(tools.getByLabel('Find a file')).toHaveValue('');
  await tools.getByRole('button', { name: 'broken.py', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Could not' })).toBeVisible();
  await expect(tabs.getByRole('tab', { name: 'a.py', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(tabs.getByRole('tab', { name: 'b.py', exact: true })).toBeVisible();
});

test('legacy key settings links redirect to the general settings sections', async ({ page }) => {
  await mock(page);
  await page.goto('/settings/providers?source=bookmark');
  await expect(page).toHaveURL('/settings/model-providers?source=bookmark');
  await expect(page.getByRole('heading', { name: 'Model providers', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Model providers', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await page.goto('/settings/agent-keys');
  await expect(page).toHaveURL('/settings/api-keys');
  await expect(page.getByRole('heading', { name: 'API keys', exact: true })).toBeVisible();
  await expect(
    page
      .getByRole('group', { name: 'Access' })
      .getByRole('link', { name: 'API keys', exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-settings-api-keys.png' });
  await expect(page.getByRole('link', { name: 'API keys', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await page.getByRole('link', { name: 'Profile', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Profile', exact: true })).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-settings-profile.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'Access', exact: true })).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-settings-profile-mobile.png' });
});

test('recovery settings actions use dismissible toasts without moving the form', async ({
  page,
}) => {
  await mock(page);
  let failSave = true;
  await page.route('**/api/v1/auth/reauthenticate', (route) =>
    route.fulfill({ json: { accepted: true } }),
  );
  await page.route('**/api/v1/account/email**', (route) => {
    const request = route.request();
    if (request.method() === 'PUT' && failSave)
      return route.fulfill({ status: 409, json: { error: { code: 'recovery_conflict' } } });
    if (request.method() === 'POST') return route.fulfill({ json: { accepted: true } });
    return route.fulfill({ json: { verified_email: null, pending_email: 'pending@example.com' } });
  });
  await page.goto('/settings/recovery');
  await expect(page.getByText('Pending verification: pending@example.com')).toBeVisible();
  await page.getByLabel('Recovery email').fill('pending@example.com');
  await page.getByLabel('Current password').fill('current-password');
  const before = await page.getByLabel('Recovery email').boundingBox();
  await page.getByRole('button', { name: 'Verify recovery email' }).click();
  await expect(page.getByRole('alert')).toHaveText(
    'This email is already verified for another account.',
  );
  expect(await page.getByLabel('Recovery email').boundingBox()).toEqual(before);
  await page.getByRole('button', { name: 'Dismiss notification' }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  failSave = false;
  await page.getByLabel('Current password').fill('current-password');
  await page.getByRole('button', { name: 'Verify recovery email' }).click();
  await expect(page.getByRole('status')).toHaveText('Check your email for a verification link.');
  expect(await page.getByLabel('Recovery email').boundingBox()).toEqual(before);
  await page.getByRole('button', { name: 'Resend verification' }).click();
  await expect(page.getByRole('status')).toHaveText(
    'Verification email requested; the earlier link no longer works.',
  );
  expect(await page.getByLabel('Recovery email').boundingBox()).toEqual(before);
});

test('old project bookmarks retain their query and fragment after navigation', async ({ page }) => {
  await mock(page);
  await page.goto(`/workspaces/${projectId}/overview?from=bookmark#notes`);
  await expect(page).toHaveURL(
    new RegExp(`/projects/${projectId}/overview\\?from=bookmark#notes$`),
  );
  await expect(
    page.getByRole('complementary', { name: 'Project navigation' }).first(),
  ).toBeVisible();
});

test('saved workbench tabs and dimensions survive the project route cutover', async ({ page }) => {
  await mock(page);
  const key = `polycolab.workbench.v2:ada:${projectId}`;
  const oldHref = `/workspaces/${projectId}/objects/${objectId}?from=saved#proof`;
  await page.addInitScript(
    ({ key, oldHref, sessionHref }) => {
      localStorage.setItem(
        key,
        JSON.stringify({
          tabs: [{ href: oldHref }, { href: sessionHref }],
          activeHref: oldHref,
          agentWidth: 305,
          rightWidth: 350,
        }),
      );
    },
    { key, oldHref, sessionHref: `/workspaces/${projectId}/sessions/${sessionId}` },
  );
  await page.goto(`/projects/${projectId}/overview`);
  await page
    .getByRole('navigation', { name: 'Project sections' })
    .getByRole('link', { name: 'Project', exact: true })
    .click();
  await expect(page).toHaveURL(oldHref.replace('/workspaces/', '/projects/'));
  await expect(page.getByRole('main').getByRole('heading', { name: revision.title })).toBeVisible();
  await expect(page.getByRole('separator', { name: 'Resize left panel' })).toHaveAttribute(
    'aria-valuenow',
    '305',
  );
  await expect(page.getByRole('separator', { name: 'Resize tools' })).toHaveAttribute(
    'aria-valuenow',
    '350',
  );
  await expect
    .poll(() =>
      page.evaluate(
        (key) =>
          JSON.parse(localStorage.getItem(key)!).tabs.every((tab: { href: string }) =>
            tab.href.startsWith('/projects/'),
          ),
        key,
      ),
    )
    .toBe(true);
});
