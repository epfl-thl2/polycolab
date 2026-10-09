import { afterEach, describe, expect, it, vi } from 'vitest';

import { createAgentSessionsApi } from '../../../src/web/src/lib/agent-sessions-api';

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('agent sessions API adapter', () => {
  it('uses the generated paths and refreshed bearer token', async () => {
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init);
      requests.push(request);
      return new Response(
        JSON.stringify([{ id: 'profile', display_name: 'Local', model_id: 'm' }]),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    });
    const token = 'new-token';
    const api = createAgentSessionsApi({
      baseUrl: 'https://api.example.test',
      getAccessToken: () => token,
    });
    const result = await api.listProfiles();
    expect(result.items[0]?.id).toBe('profile');
    expect(requests[0]?.url).toContain('/api/v1/gateway/profiles');
    expect(requests[0]?.headers.get('Authorization')).toBe(`Bearer ${token}`);
  });

  it('does not leak credentials into the browser adapter contract', () => {
    expect(Object.keys(createAgentSessionsApi())).not.toContain('apiKey');
  });
});
