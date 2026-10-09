import { afterEach, expect, it, vi } from 'vitest';
import { createPublicationApi } from '../../../src/web/src/lib/publication-api';

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

it('uses the generated publication routes, exact cursor, and confirmation retry key', async () => {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(new Request(input, init));
    return new Response(JSON.stringify({ items: [], next_cursor: null }), {
      headers: { 'content-type': 'application/json' },
    });
  });
  const api = createPublicationApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'owner-token',
  });
  const selection = { workspace_id: 'project-a', object_version_ids: ['proof-r2'] };
  await api.preview(selection);
  await api.confirm(
    { ...selection, preview_digest: 'digest-a', reason: 'Reviewed exact output' },
    'confirm-key',
  );
  await api.history('project-a', 10, 'history-next');
  await api.publicManifest('manifest-a');

  expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
    '/api/v1/publication/preview',
    '/api/v1/publication/confirm',
    '/api/v1/publication/history',
    '/api/v1/publications/manifest-a',
  ]);
  expect(requests[1]!.headers.get('Idempotency-Key')).toBe('confirm-key');
  expect(await requests[0]!.json()).toEqual(selection);
  expect(await requests[1]!.json()).toEqual({
    ...selection,
    preview_digest: 'digest-a',
    reason: 'Reviewed exact output',
  });
  expect(Object.fromEntries(new URL(requests[2]!.url).searchParams)).toEqual({
    workspace_id: 'project-a',
    limit: '10',
    cursor: 'history-next',
  });
  expect(
    requests
      .slice(0, 3)
      .every((request) => request.headers.get('Authorization') === 'Bearer owner-token'),
  ).toBe(true);
  expect(requests[3]!.headers.get('Authorization')).toBe('Bearer owner-token');
});
