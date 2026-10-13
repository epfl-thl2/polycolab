import { afterEach, expect, it, vi } from 'vitest';

import { createExternalAgentApi } from '../../../src/web/src/lib/external-agent-api';

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

it('authenticates account key management and private project run inspection', async () => {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init);
    requests.push(request.clone());
    if (request.method === 'POST') {
      return Response.json({
        id: 'credential-a',
        project_id: null,
        scope_kind: 'ACCOUNT',
        sponsor_user_id: 'user-a',
        name: 'Lean helper',
        secret: 'shown-once',
        expires_at: '2026-09-10T10:00:00Z',
        created_at: '2026-09-09T10:00:00Z',
        revoked_at: null,
        request_count: 0,
        mutation_count: 0,
        max_requests: 100,
        max_mutations: 20,
      });
    }
    if (request.method === 'DELETE') return new Response(null, { status: 204 });
    return Response.json({ items: [], next_cursor: 'next' });
  });
  const api = createExternalAgentApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'human-token',
  });

  const issued = await api.createCredential('Lean helper', 'agent-a');
  await api.listCredentials();
  await api.revokeCredential('credential-a');
  await api.listProjectRuns('project-a');

  expect(issued.secret).toBe('shown-once');
  expect(await requests[0]!.json()).toEqual({
    name: 'Lean helper',
    agent_id: 'agent-a',
    allow_library_contributions: false,
    allow_reviews: false,
  });
  expect(
    requests
      .slice(0, 3)
      .every((request) => request.headers.get('Authorization') === 'Bearer human-token'),
  ).toBe(true);
  expect(requests[3]!.headers.get('Authorization')).toBe('Bearer human-token');
  expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
    '/api/v1/account/agent-keys',
    '/api/v1/account/agent-keys',
    '/api/v1/account/agent-keys/credential-a',
    '/api/v1/projects/project-a/runs',
  ]);
});
