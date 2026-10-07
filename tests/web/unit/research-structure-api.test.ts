import { afterEach, expect, it, vi } from 'vitest';
import { createResearchStructureApi } from '../../../web/src/lib/research-structure-api';

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function mockRequests() {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(new Request(input, init));
    return new Response(JSON.stringify({ items: [], next_cursor: null }), {
      headers: { 'content-type': 'application/json' },
    });
  });
  return requests;
}

it('keeps attempts and assurance exact-revision pinned with supplied credentials', async () => {
  const requests = mockRequests();
  const api = createResearchStructureApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'private-token',
  });
  await api.publicAttempts('object-a', 'revision-r2', { limit: 10, cursor: 'next' });
  await api.publicAssurance('revision-r2', 20, 'event-a');
  await api.publicCurrentAssurance('revision-r2', 20, 'current-a');

  expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
    '/api/v1/research/objects/object-a/attempts',
    '/api/v1/assurance/revision-r2',
    '/api/v1/assurance/revision-r2/current',
  ]);
  expect(Object.fromEntries(new URL(requests[0]!.url).searchParams)).toEqual({
    target_object_version_id: 'revision-r2',
    limit: '10',
    cursor: 'next',
  });
  expect(Object.fromEntries(new URL(requests[1]!.url).searchParams)).toEqual({
    limit: '20',
    cursor: 'event-a',
  });
  expect(Object.fromEntries(new URL(requests[2]!.url).searchParams)).toEqual({
    limit: '20',
    cursor: 'current-a',
  });
  expect(
    requests.every((request) => request.headers.get('Authorization') === 'Bearer private-token'),
  ).toBe(true);
});

it('uses generated private routes, pagination and stable mutation keys', async () => {
  const requests = mockRequests();
  const api = createResearchStructureApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'human-token',
  });
  await api.attempts('object-a', {
    workspace_id: 'project-a',
    target_object_version_id: 'revision-r2',
    cursor: 'attempt-next',
  });
  await api.currentAssurance('revision-r2', 'project-a', 25, 'current-next');
  await api.writeHumanNote(
    'object-a',
    { workspace_id: 'project-a', base_revision_id: 'note-r1', body_md: 'private' },
    'note-key',
  );
  await api.reportProgress(
    'object-a',
    {
      workspace_id: 'project-a',
      object_version_id: 'revision-r2',
      status: 'PARTIAL',
      detail_md: 'work',
    },
    'progress-key',
  );
  await api.endorse(
    {
      workspace_id: 'project-a',
      object_version_id: 'revision-r2',
      active: true,
      rationale: 'reviewed',
    },
    'endorsement-key',
  );

  expect(
    requests.every((request) => request.headers.get('Authorization') === 'Bearer human-token'),
  ).toBe(true);
  expect(new URL(requests[0]!.url).searchParams.get('cursor')).toBe('attempt-next');
  expect(new URL(requests[1]!.url).pathname).toBe('/api/v1/assurance/revision-r2/current');
  expect(Object.fromEntries(new URL(requests[1]!.url).searchParams)).toEqual({
    workspace_id: 'project-a',
    limit: '25',
    cursor: 'current-next',
  });
  expect(requests.slice(2).map((request) => request.headers.get('Idempotency-Key'))).toEqual([
    'note-key',
    'progress-key',
    'endorsement-key',
  ]);
  expect(await requests[2]!.json()).toMatchObject({
    base_revision_id: 'note-r1',
    body_md: 'private',
  });
  expect(await requests[3]!.json()).toMatchObject({
    object_version_id: 'revision-r2',
    status: 'PARTIAL',
  });
});

it('resolves exact revision displays through one authenticated bounded request', async () => {
  const requests = mockRequests();
  const api = createResearchStructureApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'human-token',
  });

  await api.objectVersionDisplays({
    workspace_id: 'project-a',
    object_version_ids: ['claim-r2', 'lemma-r4'],
  });

  expect(requests).toHaveLength(1);
  expect(new URL(requests[0]!.url).pathname).toBe('/api/v1/research/versions/display');
  expect(requests[0]!.method).toBe('POST');
  expect(requests[0]!.headers.get('Authorization')).toBe('Bearer human-token');
  expect(await requests[0]!.json()).toEqual({
    workspace_id: 'project-a',
    object_version_ids: ['claim-r2', 'lemma-r4'],
  });
});
