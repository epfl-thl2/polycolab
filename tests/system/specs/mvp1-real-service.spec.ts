import { randomUUID } from 'node:crypto';

import { expect, test, type APIRequestContext } from '@playwright/test';

const apiBaseUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';
const providerUrl = process.env.POLYCOLAB_INTEGRATION_PROVIDER_URL ?? 'http://127.0.0.1:18080';

function memberHeaders(token = 'owner') {
  return { Authorization: `Bearer ${token}` };
}

async function api<T>(
  request: APIRequestContext,
  method: 'get' | 'post' | 'patch' | 'delete',
  path: string,
  options: { token?: string; data?: unknown } = {},
): Promise<{ status: number; body: T }> {
  const response = await request[method](`${apiBaseUrl}${path}`, {
    headers: options.token === null ? undefined : memberHeaders(options.token),
    data: options.data,
  });
  return { status: response.status(), body: (await response.json()) as T };
}

test('MVP-1 collaboration runs through PostgreSQL, API, built-in worker, and browser', async ({
  page,
  request,
}) => {
  const project = await api<{ id: string }>(request, 'post', '/api/v1/projects', {
    data: { name: `Integration project ${Date.now()}`, visibility: 'PRIVATE' },
  });
  expect(project.status).toBe(201);
  const projectId = project.body.id;
  const source = await api<{ id: string; current_revision_id: string }>(
    request,
    'post',
    `/api/v1/projects/${projectId}/objects`,
    { data: { kind: 'CLAIM', title: 'Exact source r1', content_md: 'r1 only: source context' } },
  );
  expect(source.status).toBe(201);
  const r1 = source.body.current_revision_id;
  const r2 = await api<{ current_revision_id: string }>(
    request,
    'post',
    `/api/v1/objects/${source.body.id}/revisions`,
    {
      data: {
        base_revision_id: r1,
        title: 'Later human revision r2',
        content_md: 'r2 must not enter the pinned context',
      },
    },
  );
  expect(r2.status).toBe(201);
  const profile = await api<{ id: string }>(request, 'post', '/api/v1/gateway/profiles', {
    data: {
      display_name: 'Deterministic provider',
      // Profile validation requires a globally routable address. The test-only
      // API entrypoint replaces only the pinned byte transport after validation.
      base_url: 'https://8.8.8.8/v1',
      model_id: 'integration-model',
      api_key: 'integration-secret-never-leaves-the-local-fake-provider',
    },
  });
  expect(profile.status).toBe(201);

  // The browser is a real dev server. This interception adds a test bearer
  // header only; every response still comes from the running FastAPI service.
  await page.route('**/auth/config', (route) => route.fulfill({ json: { mode: 'local' } }));
  await page.route('**/auth/me', (route) =>
    route.fulfill({
      json: { authenticated: true, username: 'owner', display_name: 'MVP-1 Owner' },
    }),
  );
  await page.route(`${apiBaseUrl}/api/v1/**`, async (route) => {
    await route.continue({
      headers: { ...route.request().headers(), Authorization: 'Bearer owner' },
    });
  });
  await page.goto(`/projects/${projectId}/sessions`);
  await expect(page.getByRole('heading', { name: 'Private sessions' })).toBeVisible();
  await page.getByLabel('Agent').selectOption({ label: 'Researcher · v1' });
  await page.getByRole('button', { name: 'New session' }).click();
  await expect(page.getByLabel('Message')).toBeVisible();

  // Attach the manifest through the real API because the MVP chat form does
  // not yet expose attachment selection. The remainder of the flow is browser
  // driven and receives no mocked service responses.
  const sessions = await api<Array<{ id: string }>>(
    request,
    'get',
    `/api/v1/agent-sessions?project_id=${projectId}`,
  );
  expect(sessions.status).toBe(200);
  const sessionId = sessions.body[0]?.id;
  expect(sessionId).toBeTruthy();
  const queued = await api<{ run: { id: string } }>(
    request,
    'post',
    `/api/v1/agent-sessions/${sessionId}/messages`,
    {
      data: {
        client_request_id: randomUUID(),
        content_md: 'Inspect only the attached exact revision.',
        gateway_profile_id: profile.body.id,
        context_object_version_ids: [r1],
      },
    },
  );
  expect(queued.status).toBe(202);
  await expect(page.getByText('Findings are ready for review.')).toBeVisible({ timeout: 30_000 });

  const events = await request.get(`${apiBaseUrl}/api/v1/agent-runs/${queued.body.run.id}/events`, {
    headers: memberHeaders(),
  });
  expect(events.status()).toBe(200);
  const eventIds = (await events.text())
    .split('\n')
    .filter((line) => line.startsWith('id: '))
    .map((line) => Number(line.slice(4)));
  expect(eventIds).toEqual([...eventIds].sort((left, right) => left - right));
  expect(new Set(eventIds).size).toBe(eventIds.length);
  const replay = await request.get(`${apiBaseUrl}/api/v1/agent-runs/${queued.body.run.id}/events`, {
    headers: { ...memberHeaders(), 'Last-Event-ID': String(eventIds.at(-1)) },
  });
  expect(replay.status()).toBe(200);
  expect((await replay.text()).match(/^id: /m)).toBeNull();

  const proposals = await api<Array<{ id: string }>>(
    request,
    'get',
    `/api/v1/projects/${projectId}/proposals`,
  );
  expect(proposals.status).toBe(200);
  const proposalId = proposals.body[0]?.id;
  expect(proposalId).toBeTruthy();
  await page.goto(`/projects/${projectId}/proposals/${proposalId}`);
  await expect(page.getByText('Exact source r1')).toBeVisible();
  await expect(page.getByText('r2 must not enter the pinned context')).toHaveCount(0);
  await page.getByLabel('Select change 1').check();
  const editedChange = page.locator('section.card').filter({
    has: page.getByRole('checkbox', { name: 'Select change 2' }),
  });
  await editedChange.getByLabel('Title').fill('Edited finding');
  await editedChange.getByLabel('Research text (Markdown)').fill('edited');
  await page.getByLabel('Select change 2').check();
  await page.getByLabel('Decision for change 3').selectOption('REJECT');
  await page.getByLabel('Reason for selected rejections').fill('Not supported by the source.');
  await page.getByLabel('Select change 3').check();
  await page.getByRole('button', { name: 'Apply 3 selected decisions' }).click();
  await expect(page.getByText('Selected decisions applied together.')).toBeVisible();

  const publicized = await api(request, 'patch', `/api/v1/projects/${projectId}`, {
    data: { visibility: 'PUBLIC' },
  });
  expect(publicized.status).toBe(422);
  const accepted = await api(request, 'get', `/api/v1/projects/${projectId}/objects`);
  expect(JSON.stringify(accepted.body)).toContain('Accepted finding');
  expect(JSON.stringify(accepted.body)).toContain('Edited finding');
  expect(JSON.stringify(accepted.body)).not.toContain('Rejected finding');
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  const removedPage = await page.goto(`/public/projects/${projectId}`);
  expect(removedPage?.status()).toBe(404);
  await expect(page.getByText('Accepted finding')).toHaveCount(0);
  await expect(page.getByText('Edited finding')).toHaveCount(0);
  await expect(page.getByText('Rejected finding')).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Agent chat' })).toHaveCount(0);

  const providerCalls = await request.get(`${providerUrl}/__test__/calls`);
  const providerBodies = (await providerCalls.json()) as Array<{
    messages: Array<{ role: string; content?: string }>;
  }>;
  expect(
    providerBodies.some((body) =>
      JSON.stringify(body.messages).includes('r1 only: source context'),
    ),
  ).toBe(true);
  expect(
    providerBodies.some((body) => JSON.stringify(body.messages).includes('r2 must not enter')),
  ).toBe(false);
});
