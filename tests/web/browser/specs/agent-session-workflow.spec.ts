import { expect, test, type Page } from '../fixtures';
import { messageItemFixture, runFixture, sessionFixture } from '../../unit/session-fixtures';

const projectId = '11111111-1111-1111-1111-111111111111';

async function authenticate(page: Page) {
  await page.route('**/auth/config', (route) => route.fulfill({ json: { mode: 'local' } }));
  await page.route('**/auth/me', (route) =>
    route.fulfill({
      json: { authenticated: true, username: 'contributor', display_name: 'Contributor' },
    }),
  );
}

test('read-only member has no browser agent controls', async ({ page }) => {
  await authenticate(page);
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,
          email_recovery: true,
        },
      });
    const body = path.endsWith(`/projects/${projectId}`)
      ? {
          id: projectId,
          name: 'Private project',
          description: null,
          visibility: 'PRIVATE',
          archived_at: null,
          current_user_role: 'READ_ONLY',
        }
      : [];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        Array.isArray(body) && /\/(objects|versions|comments|relations|artifacts)$/.test(path)
          ? { items: body, next_cursor: null }
          : body,
      ),
    });
  });
  await page.goto(`/projects/${projectId}/sessions/new`);
  await expect(page.getByRole('heading', { name: 'Private sessions', level: 1 })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Agent chat' })).toHaveCount(0);
});

test('contributor can create a session and queue a chat turn', async ({ page }) => {
  await authenticate(page);
  let messages: ReturnType<typeof messageItemFixture>[] = [];
  let run: ReturnType<typeof runFixture> | undefined;
  let submittedType = '';
  let sharedMode = '';
  const session = sessionFixture({ project_id: projectId });
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/agent-capabilities')
      return route.fulfill({
        json: {
          sessions: true,
          execution_available: true,
          hosted_agents: false,
        },
      });
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,
          email_recovery: true,
        },
      });
    if (path.endsWith('/platform-agents'))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'agent-1', agent_kind: 'RESEARCHER', version: 1, display_name: 'Researcher' },
          { id: 'agent-2', agent_kind: 'CRITIC', version: 1, display_name: 'Critic' },
        ]),
      });
    if (path.endsWith('/gateway/profiles'))
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'profile-1',
            display_name: 'Test gateway',
            base_url: 'https://example.test',
            model_id: 'model',
          },
        ]),
      });
    if (path.endsWith('/sessions') && request.method() === 'GET')
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify([]) });
    if (path.endsWith('/sessions') && request.method() === 'POST')
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(session),
      });
    if (path.endsWith(`/sessions/${session.id}`) && request.method() === 'GET')
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(session) });
    if (path.endsWith('/items') && request.method() === 'GET')
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ items: messages, next_cursor: null }),
      });
    if (path.endsWith('/events') && request.method() === 'POST') {
      const input = request.postDataJSON();
      if (input.type === 'interrupt' && run) {
        run = { ...run, status: 'CANCELLED', can_interrupt: false };
        return route.fulfill({ status: 202, json: { type: 'interrupt', run } });
      }
      submittedType = input.type;
      messages = [
        messageItemFixture({
          session_id: session.id,
          data: { role: 'user', content_md: input.content_md },
        }),
      ];
      run = runFixture({ session_id: session.id });
      return route.fulfill({ status: 202, json: { type: 'message', item: messages[0], run } });
    }
    if (path.endsWith('/stream'))
      return route.fulfill({ contentType: 'text/event-stream', body: ': heartbeat\n\n' });
    if (path.endsWith('/runs')) return route.fulfill({ json: run ? [run] : [] });
    if (path.endsWith('/sharing') && request.method() === 'PATCH') {
      sharedMode = request.postDataJSON().mode;
      session.sharing = sharedMode as typeof session.sharing;
      return route.fulfill({ json: { mode: session.sharing, can_manage: true } });
    }
    if (path.endsWith(`/sessions/${session.id}`) && request.method() === 'PATCH') {
      const input = request.postDataJSON();
      if ('title' in input) session.title = input.title;
      if ('archived' in input) {
        session.status = input.archived ? 'archived' : 'active';
        session.capabilities.can_send = !input.archived;
      }
      return route.fulfill({ json: session });
    }
    const body = path.endsWith(`/projects/${projectId}`)
      ? {
          id: projectId,
          name: 'Prime Patterns',
          description: null,
          visibility: 'PUBLIC',
          archived_at: null,
          current_user_role: 'CONTRIBUTOR',
        }
      : [];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        Array.isArray(body) &&
          /\/(objects|revisions|comments|relations|artifacts|project-references)$/.test(path)
          ? { items: body, next_cursor: null }
          : body,
      ),
    });
  });
  await page.goto(`/projects/${projectId}/sessions/new`);
  await expect(page.getByLabel('Message the agent')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Choose agent' })).toContainText('Researcher');
  await expect(page.getByLabel('AI provider')).toHaveCount(0);
  await page.getByLabel('Message the agent').fill('Explore this claim.');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page).toHaveURL(`/projects/${projectId}/sessions/${session.id}`);
  await expect(page.getByText('Explore this claim.')).toBeVisible();
  expect(submittedType).toBe('message');
  await page.reload();
  await expect(page.getByText('Explore this claim.')).toBeVisible();
  await page.getByRole('button', { name: 'Sharing', exact: true }).click();
  await page.getByLabel('Project access').selectOption('project_contributable');
  await page.getByRole('button', { name: 'Save sharing', exact: true }).click();
  expect(sharedMode).toBe('project_contributable');
  await page.getByRole('button', { name: 'Stop agent', exact: true }).click();
  await expect.poll(() => run?.status).toBe('CANCELLED');
  await page.getByRole('button', { name: 'Archive session', exact: true }).click();
  await expect(page.getByText('This session is archived.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toHaveCount(0);
});
