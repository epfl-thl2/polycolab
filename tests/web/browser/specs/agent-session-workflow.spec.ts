import { expect, test, type Page } from '../fixtures';
import { claimVersion } from '../../unit/version-fixtures';

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

test('read-only member has no browser agent controls', async ({ page }) => {
  await authenticate(page);
  await page.route('**/api/v1/**', async (route) => {
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
    const body = path.endsWith(`/workspaces/${projectId}`)
      ? {
          id: projectId,
          name: 'Private project',
          description: null,
          visibility: 'PRIVATE',
          archived_at: null,
          current_user_role: 'READ_ONLY',
        }
      : path.endsWith('/objects')
        ? []
        : path.includes('/neighborhood')
          ? { object_version_id: revisionId, relationships: [], nodes: [] }
          : path.endsWith(`/objects/${objectId}`)
            ? {
                id: objectId,
                workspace_id: projectId,
                kind: 'STATEMENT',
                current_object_version_id: revisionId,
                current_object_version: claimVersion({
                  id: revisionId,
                  object_id: objectId,
                  number: 1,
                  previous_object_version_id: null,
                  content: { ...claimVersion().content, title: 'Claim', content_md: 'A claim.' },
                }),
                authorship: claimVersion().authorship,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
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
  await page.goto(`/projects/${projectId}/objects/${objectId}`);
  await expect(page.getByRole('heading', { name: 'Claim', level: 1 })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Agent chat' })).toHaveCount(0);
});

test('contributor can create a session and queue a chat turn', async ({ page }) => {
  await authenticate(page);
  let messages: Array<Record<string, unknown>> = [];
  const session = {
    id: 'session-1',
    workspace_id: projectId,
    agent_version_id: 'agent-1',
    agent_kind: 'RESEARCHER',
    agent_version: 1,
    agent_display_name: 'Researcher',
    created_by_user_id: 'user-1',
    title: null,
    status: 'ACTIVE',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    archived_at: null,
  };
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/api/v1/agent-capabilities')
      return route.fulfill({
        json: {
          sessions: true,
          execution_available: true,
          hosted_agents: false,
          verification: false,
        },
      });
    if (new URL(route.request().url()).pathname === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,

          verification_submission: true,
          verification_execution: false,
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
    if (path.endsWith('/agent-sessions') && request.method() === 'GET')
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify([]) });
    if (path.endsWith('/agent-sessions') && request.method() === 'POST')
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(session),
      });
    if (path.endsWith(`/agent-sessions/${session.id}`) && request.method() === 'GET')
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(session) });
    if (path.endsWith('/messages') && request.method() === 'GET')
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(messages) });
    if (path.endsWith('/messages') && request.method() === 'POST') {
      messages = [
        {
          id: 'message-1',
          session_id: session.id,
          sequence: 1,
          role: 'USER',
          author_user_id: 'user-1',
          content_md: 'Explore this claim.',
          created_at: '2026-01-01T00:00:00Z',
        },
      ];
      return route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          message: messages[0],
          run: {
            id: 'run-1',
            session_id: session.id,
            workspace_id: projectId,
            request_message_id: 'message-1',
            parent_run_id: null,
            queue_sequence: 1,
            status: 'QUEUED',
            attempt: 0,
            cancel_requested_at: null,
            deadline_at: null,
            started_at: null,
            finished_at: null,
            failure_code: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        }),
      });
    }
    if (path.endsWith('/events'))
      return route.fulfill({
        contentType: 'text/event-stream',
        body: 'id: 1\nevent: completed\ndata: {"run_id":"run-1","cursor":1,"kind":"COMPLETED","payload":{"content_md":"Done."},"occurred_at":"2026-01-01T00:00:00Z"}\n\n',
      });
    const body = path.endsWith(`/workspaces/${projectId}`)
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
        Array.isArray(body) && /\/(objects|revisions|comments|relations|artifacts)$/.test(path)
          ? { items: body, next_cursor: null }
          : body,
      ),
    });
  });
  await page.goto(`/workspaces/${projectId}/sessions/new`);
  await expect(page.getByLabel('Message the agent')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Choose agent' })).toContainText('Researcher');
  await expect(page.getByLabel('Gateway profile')).toHaveCount(0);
  await page.getByLabel('Message the agent').fill('Explore this claim.');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page).toHaveURL(`/workspaces/${projectId}/sessions/${session.id}`);
  await expect(page.getByText('Explore this claim.')).toBeVisible();
});
