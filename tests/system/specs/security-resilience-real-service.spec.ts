import { randomUUID } from 'node:crypto';

import { expect, test, type APIRequestContext } from '@playwright/test';

const apiBaseUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';

function headers(token = 'owner') {
  return { Authorization: `Bearer ${token}` };
}

async function call<T>(
  request: APIRequestContext,
  method: 'get' | 'post' | 'delete',
  path: string,
  input: { token?: string; data?: unknown } = {},
): Promise<{ status: number; body: T }> {
  const response = await request[method](`${apiBaseUrl}${path}`, {
    headers: headers(input.token),
    data: input.data,
  });
  const text = await response.text();
  return { status: response.status(), body: (text ? JSON.parse(text) : undefined) as T };
}

test('revoked memberships block active-session SSE reconnect and cross-project session reads', async ({
  request,
}) => {
  const first = await call<{ id: string }>(request, 'post', '/api/v1/projects', {
    data: { name: `Revocation ${Date.now()}` },
  });
  const second = await call<{ id: string }>(request, 'post', '/api/v1/projects', {
    data: { name: `Other project ${Date.now()}` },
  });
  const contributor = await call<{ id: string }>(request, 'get', '/api/v1/users/me', {
    token: 'contributor',
  });
  const membership = await call(request, 'post', `/api/v1/projects/${first.body.id}/members`, {
    data: { user_id: contributor.body.id, role: 'CONTRIBUTOR' },
  });
  expect(membership.status).toBe(201);
  const profile = await call<{ id: string }>(request, 'post', '/api/v1/gateway/profiles', {
    token: 'contributor',
    data: {
      display_name: 'Contributor provider',
      base_url: 'https://8.8.8.8/v1',
      model_id: 'integration-model',
      api_key: 'integration-secret',
    },
  });
  const session = await call<{ id: string }>(request, 'post', '/api/v1/agent-sessions', {
    token: 'contributor',
    data: { project_id: first.body.id, agent_kind: 'CRITIC' },
  });
  const queued = await call<{ run: { id: string } }>(
    request,
    'post',
    `/api/v1/agent-sessions/${session.body.id}/messages`,
    {
      token: 'contributor',
      data: {
        client_request_id: randomUUID(),
        content_md: 'This reconnect must be revoked.',
        gateway_profile_id: profile.body.id,
      },
    },
  );
  expect(queued.status).toBe(202);
  const removed = await call(
    request,
    'delete',
    `/api/v1/projects/${first.body.id}/members/${contributor.body.id}`,
  );
  expect(removed.status).toBe(204);
  const reconnect = await request.get(
    `${apiBaseUrl}/api/v1/agent-runs/${queued.body.run.id}/events`,
    {
      headers: { ...headers('contributor'), 'Last-Event-ID': '1' },
    },
  );
  expect(reconnect.status()).toBe(404);

  const ownerSession = await call<{ id: string }>(request, 'post', '/api/v1/agent-sessions', {
    data: { project_id: second.body.id, agent_kind: 'RESEARCHER' },
  });
  const crossProject = await request.get(
    `${apiBaseUrl}/api/v1/agent-sessions/${ownerSession.body.id}`,
    {
      headers: headers('contributor'),
    },
  );
  expect(crossProject.status()).toBe(404);
});

test('provider faults finish as normalized failures without provider credential disclosure', async ({
  request,
}) => {
  const project = await call<{ id: string }>(request, 'post', '/api/v1/projects', {
    data: { name: `Provider fault ${Date.now()}` },
  });
  const profile = await call<{ id: string }>(request, 'post', '/api/v1/gateway/profiles', {
    data: {
      display_name: 'Failing provider',
      base_url: 'https://8.8.8.8/v1',
      model_id: 'integration-provider-error',
      api_key: 'integration-secret',
    },
  });
  const session = await call<{ id: string }>(request, 'post', '/api/v1/agent-sessions', {
    data: { project_id: project.body.id, agent_kind: 'CRITIC' },
  });
  const queued = await call<{ run: { id: string } }>(
    request,
    'post',
    `/api/v1/agent-sessions/${session.body.id}/messages`,
    {
      data: {
        client_request_id: randomUUID(),
        content_md: 'Trigger the deterministic provider failure.',
        gateway_profile_id: profile.body.id,
      },
    },
  );
  expect(queued.status).toBe(202);
  let body: { status: string; failure_code: string | null } | undefined;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const run = await call<{ status: string; failure_code: string | null }>(
      request,
      'get',
      `/api/v1/agent-runs/${queued.body.run.id}`,
    );
    body = run.body;
    if (body.status === 'FAILED') break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  expect(body?.status).toBe('FAILED');
  expect(body?.failure_code).toBeTruthy();
  expect(JSON.stringify(body)).not.toContain('integration-secret');
});
