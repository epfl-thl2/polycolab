import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

import { expect, test, type APIRequestContext } from '@playwright/test';

const apiBaseUrl = process.env.POLYCOLAB_INTEGRATION_API_URL ?? 'http://127.0.0.1:18000';
const composeFile = path.resolve(process.cwd(), 'tests/system/compose.yaml');

function headers(token = 'owner') {
  return { Authorization: `Bearer ${token}` };
}

async function call<T>(
  request: APIRequestContext,
  method: 'get' | 'post',
  pathValue: string,
  input: { token?: string; data?: unknown } = {},
): Promise<{ status: number; body: T }> {
  const response = await request[method](`${apiBaseUrl}${pathValue}`, {
    headers: headers(input.token),
    data: input.data,
  });
  const text = await response.text();
  return { status: response.status(), body: (text ? JSON.parse(text) : undefined) as T };
}

function eventIds(body: string): number[] {
  return body
    .split('\n')
    .filter((line) => line.startsWith('id: '))
    .map((line) => Number(line.slice(4)))
    .filter((value) => Number.isInteger(value));
}

function compose(...args: string[]): void {
  execFileSync('docker', ['compose', '-f', composeFile, ...args], {
    cwd: process.cwd(),
    env: process.env,
    stdio: 'pipe',
    timeout: 15_000,
  });
}

test('concurrent SSE reconnects replay one ordered suffix without duplication', async ({
  request,
}) => {
  const project = await call<{ id: string }>(request, 'post', '/api/v1/workspaces', {
    data: { name: `SSE load ${Date.now()}` },
  });
  expect(project.status).toBe(201);
  const profile = await call<{ id: string }>(request, 'post', '/api/v1/gateway/profiles', {
    data: {
      display_name: 'SSE load provider',
      base_url: 'https://8.8.8.8/v1',
      model_id: 'integration-model',
      api_key: 'integration-secret',
    },
  });
  const session = await call<{ id: string }>(request, 'post', '/api/v1/agent-sessions', {
    data: { workspace_id: project.body.id, agent_kind: 'RESEARCHER' },
  });
  const queued = await call<{ run: { id: string } }>(
    request,
    'post',
    `/api/v1/agent-sessions/${session.body.id}/messages`,
    {
      data: {
        client_request_id: randomUUID(),
        content_md: 'Generate a bounded sequence for reconnect testing.',
        gateway_profile_id: profile.body.id,
      },
    },
  );
  expect(queued.status).toBe(202);

  const initial = await request.get(
    `${apiBaseUrl}/api/v1/agent-runs/${queued.body.run.id}/events`,
    {
      headers: headers(),
    },
  );
  expect(initial.status()).toBe(200);
  const initialIds = eventIds(await initial.text());
  expect(initialIds.length).toBeGreaterThanOrEqual(2);
  const cursor = initialIds[0];
  const expectedSuffix = initialIds.filter((value) => value > cursor);

  const reconnects = await Promise.all(
    Array.from({ length: 8 }, () =>
      request.get(`${apiBaseUrl}/api/v1/agent-runs/${queued.body.run.id}/events`, {
        headers: { ...headers(), 'Last-Event-ID': String(cursor) },
      }),
    ),
  );
  for (const response of reconnects) {
    expect(response.status()).toBe(200);
    const replayed = eventIds(await response.text());
    expect(replayed).toEqual(expectedSuffix);
    expect(new Set(replayed).size).toBe(replayed.length);
  }
});

test('concurrent revision writes accept one base and reject stale writers', async ({ request }) => {
  const project = await call<{ id: string }>(request, 'post', '/api/v1/workspaces', {
    data: { name: `Edit contention ${Date.now()}` },
  });
  expect(project.status).toBe(201);
  const object = await call<{ id: string; current_revision_id: string }>(
    request,
    'post',
    `/api/v1/workspaces/${project.body.id}/objects`,
    { data: { kind: 'CLAIM', title: 'Shared base', content_md: 'r1' } },
  );
  expect(object.status).toBe(201);

  const writes = await Promise.all(
    Array.from({ length: 8 }, (_, index) =>
      request.post(`${apiBaseUrl}/api/v1/objects/${object.body.id}/revisions`, {
        headers: headers(),
        data: {
          base_revision_id: object.body.current_revision_id,
          title: `Concurrent r2 writer ${index}`,
          content_md: `writer ${index}`,
        },
      }),
    ),
  );
  expect(writes.filter((response) => response.status() === 201)).toHaveLength(1);
  expect(writes.filter((response) => response.status() === 409)).toHaveLength(7);

  const history = await call<Array<{ number: number }>>(
    request,
    'get',
    `/api/v1/objects/${object.body.id}/revisions`,
  );
  expect(history.status).toBe(200);
  expect(history.body.map((revision) => revision.number)).toEqual([2, 1]);
});

test('PostgreSQL outage makes readiness fail and recovers durable writes and worker runs', async ({
  request,
}) => {
  compose('stop', 'postgres');
  try {
    await expect
      .poll(async () => (await request.get(`${apiBaseUrl}/health/ready`)).status(), {
        timeout: 8_000,
        intervals: [100, 250, 500],
      })
      .toBe(503);
  } finally {
    compose('start', 'postgres');
  }

  await expect
    .poll(async () => (await request.get(`${apiBaseUrl}/health/ready`)).status(), {
      timeout: 12_000,
      intervals: [100, 250, 500, 1_000],
    })
    .toBe(200);

  const project = await call<{ id: string }>(request, 'post', '/api/v1/workspaces', {
    data: { name: `Recovered database ${Date.now()}` },
  });
  expect(project.status).toBe(201);
  const profile = await call<{ id: string }>(request, 'post', '/api/v1/gateway/profiles', {
    data: {
      display_name: 'Recovered provider',
      base_url: 'https://8.8.8.8/v1',
      model_id: 'integration-model',
      api_key: 'integration-secret',
    },
  });
  const session = await call<{ id: string }>(request, 'post', '/api/v1/agent-sessions', {
    data: { workspace_id: project.body.id, agent_kind: 'CRITIC' },
  });
  const queued = await call<{ run: { id: string } }>(
    request,
    'post',
    `/api/v1/agent-sessions/${session.body.id}/messages`,
    {
      data: {
        client_request_id: randomUUID(),
        content_md: 'Verify the recovered worker can persist a run.',
        gateway_profile_id: profile.body.id,
      },
    },
  );
  expect(queued.status).toBe(202);

  await expect
    .poll(
      async () => {
        const run = await call<{ status: string }>(
          request,
          'get',
          `/api/v1/agent-runs/${queued.body.run.id}`,
        );
        return run.body.status;
      },
      { timeout: 15_000, intervals: [100, 250, 500, 1_000] },
    )
    .toBe('COMPLETED');
});
