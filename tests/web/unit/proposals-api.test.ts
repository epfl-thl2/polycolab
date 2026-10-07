import { afterEach, describe, expect, it, vi } from 'vitest';

import { createProposalApi } from '../../../web/src/lib/proposals-api';

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('proposal API adapter', () => {
  it('uses generated proposal operations and sends the refreshed bearer token', async () => {
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init);
      requests.push(request);
      return new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    });
    const api = createProposalApi({
      baseUrl: 'https://api.example.test',
      getAccessToken: () => 'member-token',
    });

    await api.listProjectProposals('project-1');

    expect(requests[0]?.url).toContain('/api/v1/workspaces/project-1/proposals');
    expect(requests[0]?.headers.get('Authorization')).toBe('Bearer member-token');
  });

  it('keeps a stable decision key on retries and exposes HTTP conflicts', async () => {
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init);
      requests.push(request);
      return new Response(JSON.stringify({ error: { code: 'stale_proposal' } }), {
        status: 409,
        headers: { 'content-type': 'application/json' },
      });
    });
    const api = createProposalApi({ baseUrl: 'https://api.example.test' });

    await expect(
      api.decideChanges(
        'proposal-1',
        [{ change_id: 'change-1', action: 'ACCEPT' }],
        'decision-key-1',
      ),
    ).rejects.toMatchObject({ status: 409, code: 'stale_proposal' });
    expect(requests[0]?.url).toContain('/api/v1/proposals/proposal-1/decisions');
    expect(requests[0]?.headers.get('Idempotency-Key')).toBe('decision-key-1');
  });
});
