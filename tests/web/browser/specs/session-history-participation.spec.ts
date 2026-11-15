import { test, expect, type BrowserContext } from '../fixtures';
import { messageItemFixture, runFixture, sessionFixture } from '../../unit/session-fixtures';
import type { components } from '../../../../src/web/src/lib/api-client';

type Session = components['schemas']['SessionRead'];
type Item = components['schemas']['ItemPage']['items'][number];
const projectId = '11111111-1111-1111-1111-111111111111';

async function auth(context: BrowserContext, username: string) {
  await context.route('**/auth/config', (route) => route.fulfill({ json: { mode: 'local' } }));
  await context.route('**/auth/me', (route) =>
    route.fulfill({ json: { authenticated: true, username, display_name: username } }),
  );
}

test('shared contributors use their profile and read-only members receive the saved transcript', async ({
  browser,
}) => {
  const contributor = await browser.newContext();
  const reader = await browser.newContext();
  const session = sessionFixture({
    sharing: 'project_contributable',
    title: 'Shared investigation',
  });
  const items: Item[] = [
    messageItemFixture({
      data: { role: 'user', content_md: 'An initial question from the owner.' },
    }),
  ];
  let run: ReturnType<typeof runFixture> | undefined;
  let submitted: Record<string, unknown> | undefined;
  try {
    for (const [context, name, role] of [
      [contributor, 'contributor', 'CONTRIBUTOR'],
      [reader, 'reader', 'READ_ONLY'],
    ] as const) {
      await auth(context, name);
      await context.route('**/api/v1/**', async (route) => {
        const request = route.request();
        const path = new URL(request.url()).pathname;
        const view: Session = {
          ...session,
          capabilities: {
            can_send: role === 'CONTRIBUTOR',
            can_manage: false,
            can_share: false,
            can_stream: true,
          },
        };
        if (path === '/api/v1/config')
          return route.fulfill({
            json: {
              agent_execution: true,
              verification_submission: true,
              verification_execution: false,
              email_recovery: true,
            },
          });
        if (path === '/api/v1/agent-capabilities')
          return route.fulfill({
            json: {
              sessions: true,
              execution_available: true,
              hosted_agents: false,
              verification: false,
            },
          });
        if (path === `/api/v1/projects/${projectId}`)
          return route.fulfill({
            json: {
              id: projectId,
              name: 'Shared project',
              visibility: 'PRIVATE',
              current_user_role: role,
              archived_at: null,
            },
          });
        if (path === '/api/v1/sessions') return route.fulfill({ json: [view] });
        if (path === `/api/v1/sessions/${session.id}`) return route.fulfill({ json: view });
        if (path.endsWith('/items')) return route.fulfill({ json: { items, next_cursor: null } });
        if (path.endsWith('/runs'))
          return route.fulfill({
            json: run
              ? [{ ...run, can_interrupt: role === 'CONTRIBUTOR' && run.status === 'QUEUED' }]
              : [],
          });
        if (path.endsWith('/stream'))
          return route.fulfill({ contentType: 'text/event-stream', body: ': heartbeat\n\n' });
        if (path.endsWith('/account/provider-connections'))
          return route.fulfill({
            json: [
              { id: `${name}-profile`, display_name: `${name} provider`, model_id: 'test-model' },
            ],
          });
        if (path.endsWith('/platform-agents')) return route.fulfill({ json: [] });
        if (path.endsWith('/project-references') || path.endsWith('/objects'))
          return route.fulfill({ json: { items: [], next_cursor: null } });
        if (path.endsWith('/events') && request.method() === 'POST' && role === 'CONTRIBUTOR') {
          const event = request.postDataJSON();
          if (event.type === 'interrupt') {
            expect(event.run_id).toBe(run?.id);
            run = { ...run!, status: 'CANCELLED', can_interrupt: false };
            return route.fulfill({ status: 202, json: { type: 'interrupt', run } });
          }
          submitted = event;
          const item = messageItemFixture({
            id: 'participant-message',
            sequence: 2,
            author: { type: 'human', user_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' },
            data: { role: 'user', content_md: event.content_md },
          });
          items.push(item);
          run = runFixture({
            requested_by_user_id: item.author.type === 'human' ? item.author.user_id : '',
            can_read_private_context: true,
          });
          return route.fulfill({ status: 202, json: { type: 'message', item, run } });
        }
        return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } });
      });
    }
    const authorPage = await contributor.newPage();
    await authorPage.goto(`/projects/${projectId}/sessions/${session.id}`);
    await expect(authorPage.getByText('An initial question from the owner.')).toBeVisible();
    await expect(authorPage.getByRole('button', { name: 'Sharing', exact: true })).toHaveCount(0);
    await expect(
      authorPage.getByRole('button', { name: 'Archive session', exact: true }),
    ).toHaveCount(0);
    await authorPage.getByRole('tab', { name: 'Agent history', exact: true }).click();
    await authorPage.getByLabel('AI provider').selectOption('contributor-profile');
    await authorPage
      .getByLabel('Message shared with project', { exact: true })
      .fill('A second perspective from the contributor.');
    await authorPage.getByRole('button', { name: 'Send message', exact: true }).click();
    await expect(authorPage.getByText('A second perspective from the contributor.')).toBeVisible();
    expect(submitted).toMatchObject({
      type: 'message',
      provider_connection_id: 'contributor-profile',
    });
    expect(submitted).not.toHaveProperty('author');
    await authorPage.getByRole('button', { name: 'Stop agent', exact: true }).click();
    await expect.poll(() => run?.status).toBe('CANCELLED');
    const readerPage = await reader.newPage();
    await readerPage.goto(`/projects/${projectId}/sessions/${session.id}`);
    await expect(readerPage.getByText('A second perspective from the contributor.')).toBeVisible();
    await readerPage.reload();
    await expect(readerPage.getByText('An initial question from the owner.')).toBeVisible();
    await expect(readerPage.getByRole('button', { name: 'Send message', exact: true })).toHaveCount(
      0,
    );
    await expect(readerPage.getByRole('button', { name: 'Stop agent', exact: true })).toHaveCount(
      0,
    );
    await expect(readerPage.getByRole('button', { name: 'Sharing', exact: true })).toHaveCount(0);
  } finally {
    await contributor.close();
    await reader.close();
  }
});

test('retired direct history preserves unknown usage and supports rename and archive without a composer', async ({
  page,
}) => {
  await auth(page.context(), 'owner');
  const session = sessionFixture({
    project_id: null,
    origin: 'legacy_direct',
    title: 'Old investigation',
    configuration: null,
    capabilities: { can_send: false, can_manage: true, can_share: false, can_stream: false },
  });
  const run = runFixture({
    project_id: null,
    origin: 'legacy_direct',
    status: 'INTERRUPTED',
    attempt: null,
    updated_at: null,
    requested_model: 'historical-model',
    can_interrupt: false,
    can_read_private_context: false,
    usage: {
      observations: [
        {
          source: 'UNKNOWN',
          input_tokens: null,
          output_tokens: null,
          total_tokens: null,
          observed_at: null,
          execution_id: 'run-1',
          event_cursor: null,
        },
      ],
      reservations: [{ tokens: 1000, cost_microusd: 2000 }],
    },
  });
  const forbiddenRequests: string[] = [];
  await page.route('**/api/v1/**', (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === '/api/v1/config')
      return route.fulfill({
        json: {
          agent_execution: true,
          verification_submission: true,
          verification_execution: false,
          email_recovery: true,
        },
      });
    if (path === '/api/v1/sessions') {
      expect(url.searchParams.get('origin')).toBe('legacy_direct');
      return route.fulfill({ json: [session] });
    }
    if (path === `/api/v1/sessions/${session.id}`) {
      if (request.method() === 'PATCH') {
        const input = request.postDataJSON();
        if ('title' in input) session.title = input.title;
        if ('archived' in input) session.status = input.archived ? 'archived' : 'active';
      }
      return route.fulfill({ json: session });
    }
    if (path.endsWith('/items'))
      return route.fulfill({
        json: {
          items: [
            messageItemFixture({
              status: 'interrupted',
              data: { role: 'user', content_md: 'Saved historical question.' },
            }),
          ],
          next_cursor: null,
        },
      });
    if (path.endsWith('/runs')) return route.fulfill({ json: [run] });
    if (/\/(events|stream|sharing|resume)$/.test(path)) forbiddenRequests.push(path);
    return route.fulfill({ status: 404, json: { error: { code: 'not_found' } } });
  });
  await page.goto('/settings/session-history');
  await page.getByRole('link', { name: 'Old investigation', exact: true }).click();
  await expect(page.getByText('Saved historical question.')).toBeVisible();
  await page.getByText('Historical requests and usage', { exact: true }).click();
  await expect(page.getByText(/Observed tokens: input unknown, output unknown/)).toBeVisible();
  await expect(page.getByText('Reserved budget: 1000 tokens · 2000 micro-USD')).toBeVisible();
  await page.getByRole('button', { name: 'Rename', exact: true }).click();
  await page.getByLabel('Conversation title').fill('Preserved investigation');
  await page.getByRole('button', { name: 'Save title', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Preserved investigation' })).toBeVisible();
  await page.getByRole('button', { name: 'Archive history', exact: true }).click();
  await page.reload();
  await expect(page.getByText('Read-only history · archived')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send message', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Restore history', exact: true })).toBeVisible();
  expect(forbiddenRequests).toEqual([]);
});
