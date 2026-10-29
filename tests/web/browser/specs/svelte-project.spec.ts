import { plainFileEditor } from '../helpers/project-editor';
import { test, expect, type Page } from '../fixtures';
const projectId = '11111111-1111-4111-8111-111111111111';
const sessionId = '44444444-4444-4444-8444-444444444444';
const runId = '55555555-5555-4555-8555-555555555555';
const author = { id: 'author-1', display_name: 'Ada' };
const createdAt = '2026-09-05T12:00:00Z';
const project = {
  id: projectId,
  name: 'Spectral gaps',
  workspace_mode: 'git',
  description: 'Exploring expansion in finite graphs.',
  visibility: 'PUBLIC',
  current_user_role: 'OWNER',
  member_count: 3,
  archived_at: null,
  created_at: createdAt,
  updated_at: createdAt,
};

function unsignedJwt(payload: Record<string, unknown>) {
  const encode = (value: object) => Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${encode({ alg: 'none', typ: 'JWT' })}.${encode(payload)}.`;
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
  created_at: createdAt,
  updated_at: createdAt,
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
          email_recovery: true,
        },
      });
    requests.push(`${request.method()} ${path}`);
    if (request.method() === 'GET' && path === `/api/v1/projects/${projectId}/repository`)
      return route.fulfill({
        json: {
          enabled: false,
          branch: url.searchParams.get('branch') ?? 'main',
          writable: false,
          commit: null,
          files: [],
          branches: {},
        },
      });
    if (path === '/api/v1/agent-capabilities')
      return route.fulfill({
        json: {
          sessions: true,
          execution_available: true,
          hosted_agents: false,
        },
      });
    if (path === '/api/v1/account/agents')
      return route.fulfill({
        json:
          request.method() === 'POST'
            ? { id: 'agent-1', name: 'Agent', sponsor_user_id: 'author-1' }
            : { items: [], next_cursor: null },
      });
    if (path === '/api/v1/users/me')
      return route.fulfill({
        json: { id: 'author-1', username: 'ada', display_name: 'Ada', email: null },
      });
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
                created_at: createdAt,
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
    if (path.endsWith('/members') || path.endsWith('/invitations'))
      return route.fulfill({ json: [] });
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

test('public About page gives a concise introduction on desktop and mobile', async ({ page }) => {
  await mock(page);
  await page.route('**/auth/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,
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
  await page
    .getByRole('navigation', { name: 'Documentation sections' })
    .getByRole('link', { name: 'User Setup', exact: true })
    .click();
  await expect(page.getByRole('heading', { name: 'User setup', exact: true })).toBeVisible();
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
  await page
    .getByRole('article')
    .getByRole('link', { name: 'Account and security', exact: true })
    .click();
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
      pending_requested_at: createdAt,
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
    verified_at: createdAt,
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
  await page.goto('/about');
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
  let selectedUsername: string | null = null;
  await page.route('**/api/v1/users/me', (route) =>
    route.fulfill({
      json: {
        id: 'oidc-internal-user',
        username: selectedUsername,
        display_name: 'OIDC Ada',
        email: null,
      },
    }),
  );
  await page.route('**/api/v1/account/username', (route) => {
    expect(route.request().headers().authorization).toBe('Bearer oidc-access-token');
    const candidate = route.request().postDataJSON().username;
    if (candidate === 'taken')
      return route.fulfill({ status: 409, json: { error: { code: 'username_unavailable' } } });
    selectedUsername = candidate;
    return route.fulfill({
      json: {
        id: 'oidc-internal-user',
        username: selectedUsername,
        display_name: 'OIDC Ada',
        email: null,
      },
    });
  });

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

  await expect(page.getByRole('heading', { name: 'Choose your username' })).toBeVisible();
  await page.getByLabel('Username', { exact: true }).fill('taken');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('unavailable');
  await page.getByLabel('Username', { exact: true }).fill('OIDC-Ada');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  expect(selectedUsername).toBe('oidc-ada');
  await expect(page).toHaveURL(`${origin}/projects/${projectId}/sessions/new`);
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Spectral gaps', level: 1 })).toBeVisible();
  expect(projectAuthorizations).toContain('Bearer oidc-access-token');
  await page.goto('/projects');
  await expect(page.getByRole('button', { name: 'Open account menu for OIDC Ada' })).toBeVisible();
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
    created_at: createdAt,
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
  await expect(page.getByRole('status').filter({ hasText: 'API key revoked' })).toBeVisible();

  await page.reload();
  await expect(page.getByLabel('API key', { exact: true })).toHaveCount(0);
  expect(methods).toContain('POST');
  expect(methods).toContain('DELETE');
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
  for (const name of ['Your projects', 'Settings', 'Password and authentication', 'Sign out'])
    await expect(page.getByRole('menuitem', { name, exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: 'Spectral gaps', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Worktrees', exact: true })).toBeVisible();
  const url = page.url();
  await page.getByRole('button', { name: 'Open account menu', exact: true }).click();
  for (const name of ['Your projects', 'Settings', 'Password and authentication', 'Sign out'])
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
  expect(rows).toHaveLength(5);
  for (const [index, row] of rows.entries()) {
    expect(row.height).toBeGreaterThanOrEqual(36);
    expect(row.width).toBeGreaterThan(180);
    expect(row.x).toBe(rows[0].x);
    if (index > 0) expect(row.y).toBeGreaterThanOrEqual(rows[index - 1].y + rows[index - 1].height);
  }
  await page.screenshot({ path: '/tmp/polycolab-account-menu.png' });
  await page.keyboard.press('Escape');

  const destinations = [{ item: 'Settings', path: '/settings', heading: 'Settings' }];

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
    { route: `/projects/${projectId}/overview`, heading: project.name },
    { route: '/settings', heading: 'Settings' },
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
  await expect(rail.getByRole('link', { name: 'Map', exact: true })).toHaveCount(0);
  await expect(rail.getByRole('link', { name: 'Research objects', exact: true })).toHaveCount(0);
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
  await expect(page.locator('[data-feedback-toast]').getByRole('alert')).toContainText(
    'temporarily_unavailable',
  );
  await page.getByRole('button', { name: 'Dismiss notification' }).click();
  await expect(page.locator('[data-feedback-toast]')).toHaveCount(0);
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
  await expect(page.locator('.project-chat-reply .project-chat-send-reason')).toHaveText(
    'Choose an AI provider in Chat settings.',
  );
  await page.screenshot({ path: '/tmp/polycolab-enabled-chat-after.png' });
  if (!(await page.getByLabel('AI provider').isVisible()))
    await page.getByRole('tab', { name: 'Agent history', exact: true }).click();
  await page.getByLabel('AI provider').selectOption('profile-1');
  await page.getByText('Artifact context · 0 files').click();
  await page
    .getByLabel('Artifact IDs (comma or whitespace separated)')
    .fill('artifact-exact-1, artifact-exact-1');
  await page.getByLabel('Private message', { exact: true }).fill('Explore the gap.');
  await expect(page.locator('.project-chat-reply .project-chat-send-reason')).toHaveCount(0);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.locator('[data-feedback-toast]').getByRole('alert')).toContainText(
    'temporarily_unavailable',
  );
  await expect(page.getByLabel('Private message', { exact: true })).toHaveValue('Explore the gap.');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.getByLabel('Private message', { exact: true })).toHaveValue('');
  await expect(page.locator('[data-feedback-toast]')).toHaveCount(0);
  expect(bodies[1].client_request_id).toBe(bodies[0].client_request_id);
  expect(bodies[1]).not.toHaveProperty('context_object_version_ids');
  expect(bodies[1].context_artifact_ids).toEqual(['artifact-exact-1']);
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
      occurred_at: createdAt,
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
  await page.getByRole('button', { name: 'Stop agent' }).click();
  expect(cancelled).toBe(true);
  await expect(page.getByRole('button', { name: 'Resume run' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toBeVisible();
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
          created_at: createdAt,
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

test('owner settings are reachable and save details without changing visibility', async ({
  page,
}) => {
  await mock(page);
  await page.goto(`/projects/${projectId}/settings`);
  await expect(page.getByRole('dialog', { name: 'Project settings', exact: true })).toBeVisible();
  const settings = page.locator('.settings-stack');
  await expect(settings.getByRole('heading', { level: 2 })).toHaveText([
    'Switch to linear history',
    'Project details',
    'Members',
    'Project lifecycle',
  ]);
  await expect(settings.locator('.settings-section')).toHaveCount(3);
  await page.screenshot({ path: '/tmp/polycolab-project-settings.png', fullPage: true });
  await page.getByLabel('Name', { exact: true }).fill('Revised name');
  await page.getByRole('button', { name: 'Save settings' }).scrollIntoViewIfNeeded();
  const beforeSave = await settings.boundingBox();
  const request = page.waitForRequest((r) => r.method() === 'PATCH');
  await page.getByRole('button', { name: 'Save settings' }).click();
  expect((await request).postDataJSON()).toEqual({
    name: 'Revised name',
    description: project.description,
  });
  await expect(page.getByRole('status')).toContainText('Settings saved');
  await expect(page.locator('[data-toast-stack]')).toHaveCount(1);
  expect((await settings.boundingBox())?.y).toBe(beforeSave?.y);
  await page.getByRole('button', { name: 'Dismiss notification' }).click();
  await expect(page.locator('[data-feedback-toast]')).toHaveCount(0);
  await page.getByRole('button', { name: 'Save settings' }).click();
  await expect(page.locator('[data-feedback-toast]')).toContainText('Settings saved.');
  await page
    .getByRole('dialog', { name: 'Project settings', exact: true })
    .getByRole('button', { name: 'Close', exact: true })
    .click();
  await page
    .getByRole('complementary', { name: 'Project navigation', exact: true })
    .getByRole('button', { name: 'Agent connect', exact: true })
    .click();
  await expect(page.getByRole('heading', { name: 'Agent connect', exact: true })).toBeVisible();
  await expect(page.locator('[data-feedback-toast]')).toContainText('Settings saved.');
});

test('shared success toasts pause for hover and keyboard focus before expiring', async ({
  page,
}) => {
  await mock(page);
  await page.clock.install();
  await page.goto(`/projects/${projectId}/settings`);
  await page.getByRole('button', { name: 'Save settings' }).click();
  const toast = page.locator('[data-feedback-toast]').filter({ hasText: 'Settings saved.' });
  await expect(toast).toBeVisible();
  await toast.hover();
  await page.clock.runFor(6000);
  await expect(toast).toBeVisible();
  const dismiss = toast.getByRole('button', { name: 'Dismiss notification' });
  await dismiss.focus();
  await page.mouse.move(0, 0);
  await page.clock.runFor(6000);
  await expect(toast).toBeVisible();
  await page.getByLabel('Name', { exact: true }).focus();
  await page.clock.runFor(5100);
  await expect(toast).toHaveCount(0);
});

test('failed member refresh keeps cached content and reports a retryable toast', async ({
  page,
}) => {
  await mock(page);
  let fail = false;
  await page.route(new RegExp(`/api/v1/projects/${projectId}/members(?:\\?.*)?$`), (route) =>
    fail
      ? route.fulfill({ status: 503, json: { error: { code: 'unavailable' } } })
      : route.fulfill({
          json: [
            {
              user_id: '11111111-1111-4111-8111-111111111111',
              username: 'ada',
              display_name: 'Ada Lovelace',
              role: 'OWNER',
              created_at: createdAt,
            },
          ],
        }),
  );
  await page.goto(`/projects/${projectId}/settings`);
  const member = page.getByRole('listitem').filter({ hasText: 'Ada Lovelace' });
  await expect(member).toBeVisible();
  await member.scrollIntoViewIfNeeded();
  const before = await member.boundingBox();
  fail = true;
  await page.getByRole('button', { name: 'Refresh members' }).click();
  const toast = page.locator('[data-feedback-toast]').filter({ has: page.getByRole('alert') });
  await expect(toast).toBeVisible();
  await expect(member).toBeVisible();
  expect((await member.boundingBox())?.y).toBe(before?.y);
  fail = false;
  await toast.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(toast).toHaveCount(0);
  await expect(member).toBeVisible();
});

test('project owners add registered collaborators by exact username', async ({ page }) => {
  await mock(page);
  const ada = {
    user_id: '11111111-1111-4111-8111-111111111111',
    username: 'ada',
    display_name: 'Ada Lovelace',
    role: 'OWNER',
    created_at: createdAt,
  };
  const grace = {
    user_id: '22222222-2222-4222-8222-222222222222',
    username: 'grace.hopper',
    display_name: 'Grace Hopper',
    role: 'CONTRIBUTOR',
    created_at: createdAt,
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
  await expect(page.getByRole('status').filter({ hasText: 'API key replaced.' })).toBeVisible();
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
  await expect(page.getByRole('status').filter({ hasText: 'AI provider deleted.' })).toBeVisible();
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
  await expect(page.locator('figure figcaption')).toContainText('shared work by people and agents');
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
      },
    }),
  );
  await page.route('**/api/v1/agent-sessions/*/runs*', (route) =>
    route.fulfill({
      json: [
        {
          id: 'completed-run',
          status: 'COMPLETED',
          created_at: createdAt,
          failure_code: null,
        },
        {
          id: 'lost-run',
          status: 'FAILED',
          created_at: createdAt,
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
    page.getByText('Review its history before sending another message', { exact: false }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Resume run' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toBeDisabled();
  await page.getByRole('tab', { name: 'Agent history', exact: true }).click();
  await page.getByText('Files and run history', { exact: true }).click();
  await page.getByLabel('Files from completed run').selectOption('completed-run');
  await expect(page.getByRole('button', { name: 'Download Saved result.txt' })).toBeVisible();
  await expect(page.getByText('Execution unavailable', { exact: true })).toBeVisible();
});

test('public project metadata keeps files and conversations private', async ({ page }) => {
  await mock(page, '');
  await page.goto(`/projects/${projectId}/overview`);
  await expect(page.getByRole('heading', { name: project.name, exact: true })).toBeVisible();
  await expect(
    page.getByText('Project files and conversations are available to members.'),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'New file', exact: true })).toHaveCount(0);
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
  await expect(rail.getByRole('link', { name: 'Map', exact: true })).toHaveCount(0);
  await expect(rail.getByRole('link', { name: 'Research objects', exact: true })).toHaveCount(0);
  for (const [label, name] of [['Overview', 'Project']]) {
    await rail.getByRole('link', { name: label, exact: true }).click();
    const panel = page.getByRole('complementary', { name: `${name} panel`, exact: true });
    await expect(panel.getByRole('heading', { name, exact: true, level: 2 })).toBeVisible();
    await expect(page.getByRole('tablist', { name: 'Project tabs' })).toHaveCount(0);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'Navigation', exact: true });
  await expect(drawer.getByRole('link', { name: 'Map', exact: true })).toHaveCount(0);
  await expect(drawer.getByRole('link', { name: 'Research objects', exact: true })).toHaveCount(0);
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
  await page.goto(`/projects/${projectId}/overview`);
  const rail = page.getByRole('complementary', { name: 'Project navigation', exact: true });
  const panel = page.getByRole('complementary', { name: 'Project panel', exact: true });
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
    .getByRole('button', { name: 'Agent connect', exact: true });
  await agentConnect.click();
  await expect(page).toHaveURL(`/projects/${projectId}/sessions/new`);
  await expect(page.getByRole('heading', { name: 'Agent connect', exact: true })).toBeVisible();
  const instructions = page.getByRole('textbox', { name: 'Agent connection instructions' });
  await expect(instructions).toHaveValue(new RegExp(`Project ID: ${projectId}`));
  await expect(instructions).toHaveValue(new RegExp(`${new URL(page.url()).origin}/SKILL.md`));
  await expect(instructions).toHaveValue(/Project name \(data\): "/);
  await expect(instructions).toHaveValue(
    /Do not inspect other private projects or change files until I give you a specific question/,
  );
  await expect(page.getByRole('button', { name: 'Create API key' })).toBeVisible();
  await page.getByRole('button', { name: 'Create API key' }).click();
  const keyDialog = page.getByRole('dialog', { name: 'Create API key' });
  await expect(keyDialog).toBeVisible();
  await expect(keyDialog).toContainText('Default project files using your current membership');
  await keyDialog.getByLabel('Polycolab agent name').fill('Lean researcher');
  await keyDialog.getByLabel('Key name').fill('Lean helper');
  await keyDialog.getByRole('button', { name: 'Create API key' }).click();
  await expect(page.getByLabel('API key', { exact: true })).toHaveValue('shown-once-secret');
  const issuedDialog = page.getByRole('dialog', { name: 'Your API key' });
  const stack = issuedDialog.locator('[data-toast-stack]');
  await expect(stack).toHaveCount(1);
  await expect(stack.getByRole('status')).toHaveText('API key created.');
  const dismiss = stack.getByRole('button', { name: 'Dismiss notification' });
  await dismiss.focus();
  await expect(dismiss).toBeFocused();
  await dismiss.press('Enter');
  await expect(stack).toHaveCount(0);
  await expect(issuedDialog).toBeVisible();
  await page.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Your API key' })).toHaveCount(0);
  await expect(page).toHaveURL(`/projects/${projectId}/sessions/new`);
  await expect(page.getByRole('dialog', { name: 'Agent connect', exact: true })).toContainText(
    'not limited to this project',
  );
  await page
    .getByRole('dialog', { name: 'Agent connect', exact: true })
    .getByRole('button', { name: 'Close', exact: true })
    .click();
  const link = agentConnect;
  await expect(link).toHaveAttribute('aria-haspopup', 'dialog');
  await link.hover();
  await expect(page.getByRole('tooltip')).toHaveText('Agent connect');
  await expect(link.locator('svg')).toBeVisible();
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
    created_at: createdAt,
    updated_at: createdAt,
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
  let releaseRefresh!: () => void;
  const refreshGate = new Promise<void>((resolve) => (releaseRefresh = resolve));
  await page.route(`**/api/v1/projects/${projectId}/worktrees**`, async (route) => {
    if (
      route.request().method() === 'GET' &&
      head === 'b'.repeat(40) &&
      !new URL(route.request().url()).pathname.endsWith('/file')
    )
      await refreshGate;
    await route.fallback();
  });
  await page.goto(`/projects/${projectId}/files`);
  await page.getByRole('button', { name: 'notes.md', exact: true }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Initial note');
  await (await plainFileEditor(page)).fill('Updated note');
  const refreshing = page.waitForRequest(
    (request) =>
      request.method() === 'GET' &&
      request.url().includes(`/projects/${projectId}/worktrees`) &&
      head === 'b'.repeat(40),
  );
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const toast = page.locator('[data-feedback-toast]');
  await expect(toast.getByRole('status')).toHaveText('Saved.');
  await refreshing;
  try {
    await expect(
      page.getByText('Shared files changed since you opened this draft.', { exact: true }),
    ).toHaveCount(0);
  } finally {
    releaseRefresh();
  }
  await expect(page.locator('[data-toast-stack]')).toHaveCSS('position', 'fixed');
  await expect(page.locator('[data-toast-stack]')).toHaveAttribute('popover', 'manual');
  await expect(toast).toBeVisible();
  const viewport = page.viewportSize()!;
  const toastBox = (await toast.boundingBox())!;
  expect(toastBox.y + toastBox.height).toBeLessThanOrEqual(viewport.height);
  expect(toastBox.y).toBeGreaterThan(viewport.height / 2);
  await toast.getByRole('button', { name: 'Dismiss notification' }).click();
  await expect(toast).toHaveCount(0);
  expect(saved).toBe('Updated note');
  stale = true;
  await (await plainFileEditor(page)).fill('Draft to retain');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(toast.getByRole('alert')).toContainText(
    'Compare the latest version before saving again',
  );
  await expect(await plainFileEditor(page)).toHaveValue('Draft to retain');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(toast).toBeVisible();
  const mobileBox = (await toast.boundingBox())!;
  expect(mobileBox.x).toBeGreaterThanOrEqual(0);
  expect(mobileBox.x + mobileBox.width).toBeLessThanOrEqual(390);
  await toast.getByRole('button', { name: 'Dismiss notification' }).click();
  await expect(toast).toHaveCount(0);
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
  for (const section of ['Overview']) {
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
            created_at: createdAt,
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
    .getByRole('link', { name: 'Overview', exact: true })
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
    created_at: createdAt,
    updated_at: createdAt,
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
          ? { archived_at: body.archived ? createdAt : null }
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
  await expect(rail.getByRole('link', { name: 'Chat', exact: true })).toHaveCount(0);
  const composer = page.getByLabel('Message the agent').filter({ visible: true });
  await composer.fill('Keep this layout-switch draft');
  await expect(page.getByRole('tab', { name: /^New chat/ })).toHaveCount(1);
  const projectWidth = (await page.getByRole('main').boundingBox())!.width;
  for (const [label, panel] of [['Overview', 'Project panel']]) {
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
  await expect(composer).toHaveValue('Keep this layout-switch draft');
  await page.goForward();
  await expect(
    page.getByRole('complementary', { name: 'Project panel', exact: true }),
  ).toBeVisible();
  await rail.getByRole('link', { name: 'Project', exact: true }).click();
  await expect(composer).toHaveValue('Keep this layout-switch draft');
  await expect(page.getByRole('tab', { name: /^New chat/ })).toHaveCount(1);
  await expect(page.getByRole('complementary', { name: 'Worktrees', exact: true })).toBeVisible();
  await page.screenshot({ path: '/tmp/polycolab-project-layout.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByRole('link', { name: 'Chat', exact: true })).toHaveCount(0);
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

test('retired project Chat bookmarks open existing project conversations', async ({ page }) => {
  await mock(page);
  const chatRequests: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/v1/chat/'))
      chatRequests.push(request.url());
  });
  await page.goto(`/projects/${projectId}/chat`);
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/sessions$`));
  await expect(page.getByRole('heading', { name: 'All sessions', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Chat', exact: true })).toHaveCount(0);
  expect(chatRequests).toEqual([]);
});

test('LaTeX builds save all drafts, retain the PDF after failure, and cancel by worktree', async ({
  page,
}) => {
  test.setTimeout(90_000);
  await mock(page);
  let savedRevision = 'a'.repeat(40);
  const files: Record<string, string> = {
    'main.tex': '\\documentclass{article}\n\\begin{document}Hello\\end{document}',
    'chapter.tex': 'First chapter',
  };
  await page.route(`**/api/v1/projects/${projectId}/repository**`, (route) =>
    route.fulfill({
      json: {
        enabled: true,
        writable: true,
        branch: 'main',
        commit: savedRevision,
        branches: { main: 'a'.repeat(40) },
        files: Object.entries(files).map(([path, value]) => ({
          path,
          size: value.length,
          executable: false,
        })),
      },
    }),
  );
  await mockNativeFiles(
    page,
    () => [nativeTree(mainWorktreeId, 'Main', 'main', savedRevision, files)],
    (_id, path) => files[path],
    (body) => {
      expect(body.expected_revision).toBe(savedRevision);
      expect(body.changes).toHaveLength(2);
      for (const change of body.changes)
        files[change.path] = Buffer.from(change.content_base64, 'base64').toString();
      savedRevision = 'b'.repeat(40);
      return savedRevision;
    },
  );
  type Build = {
    id: string;
    project_id: string;
    worktree_id: string;
    revision: string;
    main_file: string;
    engine: string;
    status: string;
    created_at: string;
    expires_at: string;
    error: string | null;
    pdf_available: boolean;
    log_available: boolean;
  };
  const builds: Build[] = [];
  let submissions = 0;
  const url = `/api/v1/projects/${projectId}/worktrees/${mainWorktreeId}/latex-builds`;
  await page.route(`**${url}**`, (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/outputs/pdf'))
      return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' });
    if (path.endsWith('/outputs/log'))
      return route.fulfill({
        contentType: 'text/plain',
        body: './main.tex:2: Undefined control sequence.',
      });
    if (path.endsWith('/cancel')) {
      expect(path).toBe(`${url}/${builds[0].id}/cancel`);
      builds[0] = { ...builds[0], status: 'cancelled' };
      return route.fulfill({ json: builds[0] });
    }
    if (request.method() === 'POST') {
      expect(request.postDataJSON()).toMatchObject({
        revision: 'b'.repeat(40),
        main_file: 'main.tex',
        engine: 'pdflatex',
      });
      expect(request.headers()['idempotency-key']).toBeTruthy();
      submissions++;
      const build: Build = {
        id: `${submissions}`,
        project_id: projectId,
        worktree_id: mainWorktreeId,
        revision: savedRevision,
        main_file: 'main.tex',
        engine: 'pdflatex',
        status: submissions === 1 ? 'succeeded' : submissions === 2 ? 'failed' : 'running',
        created_at: new Date().toISOString(),
        expires_at: '2099-01-01T00:00:00Z',
        error: submissions === 2 ? 'latex_compile_failed' : null,
        pdf_available: submissions === 1,
        log_available: submissions === 2,
      };
      builds.unshift(build);
      return route.fulfill({ status: 202, json: build });
    }
    return route.fulfill({ json: { available: true, builds } });
  });
  await page.goto(`/projects/${projectId}/files`);
  await page.getByRole('button', { name: 'main.tex', exact: true }).click();
  await expect(page.getByLabel('Copy path: main.tex', { exact: true })).toBeVisible();
  await (await plainFileEditor(page)).fill('Updated main document');
  await page.getByRole('button', { name: 'chapter.tex', exact: true }).click();
  await expect(page.getByLabel('Copy path: chapter.tex', { exact: true })).toBeVisible();
  await (await plainFileEditor(page)).fill('Updated chapter');
  await page.getByRole('button', { name: 'LaTeX / PDF preview', exact: true }).click();
  await page.getByLabel('Main LaTeX document').selectOption('main.tex');
  await page.getByRole('button', { name: 'Save all & compile', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Download PDF' })).toBeVisible();
  expect(files).toEqual({ 'main.tex': 'Updated main document', 'chapter.tex': 'Updated chapter' });
  await page.getByRole('button', { name: 'Compile', exact: true }).click();
  await expect(page.getByRole('button', { name: /main.tex:2/ })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Download PDF' })).toBeVisible();
  await page.getByRole('button', { name: /main.tex:2/ }).click();
  await expect(await plainFileEditor(page)).toHaveValue('Updated main document');
  await page.getByRole('button', { name: 'Compile', exact: true }).click();
  await page.getByRole('button', { name: 'Cancel build', exact: true }).click();
  await expect(page.getByText('Build: cancelled', { exact: true })).toBeVisible();
});
