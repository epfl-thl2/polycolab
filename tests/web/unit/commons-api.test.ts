import { afterEach, expect, it, vi } from 'vitest';
import { createCatalogueApi } from '../../../src/web/src/lib/catalogue-api';
import { createRecordsApi } from '../../../src/web/src/lib/records-api';

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

it('creates research through the snapshot API with an explicit destination and retry key', async () => {
  let request: Request | undefined;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    request = new Request(input);
    return Response.json({ outputs: [{ entity_type: 'OBJECT_VERSION', entity_id: 'version-1' }] });
  });
  const body = {
    destination: { kind: 'library' as const, statement_object_version_id: 'statement-1' },
    snapshot: {
      kind: 'NOTE' as const,
      content: {
        title: 'Note',
        content_md: 'Full content',
        assumptions_md: 'None',
        reported_outcome: null,
        explanation_md: null,
      },
      structural_relationships: [
        { relationship_type: 'ATTACHMENT' as const, target_object_version_id: 'statement-1' },
      ],
      change_summary: null,
    },
  };
  const response = await createRecordsApi({ baseUrl: 'https://api.example.test' }).create(
    body,
    'retry-key',
  );
  expect(new URL(request!.url).pathname).toBe('/api/v1/objects');
  expect(request!.headers.get('Idempotency-Key')).toBe('retry-key');
  expect(await request!.json()).toEqual(body);
  expect(response.outputs[0]!.entity_type).toBe('OBJECT_VERSION');
});

it('sends private discovery scope and filters only to the authenticated endpoint', async () => {
  let request: Request | undefined;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    request = new Request(input);
    return new Response(JSON.stringify({ items: [], next_cursor: null }), {
      headers: { 'content-type': 'application/json' },
    });
  });
  await createRecordsApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'private-token',
  }).projectSearch({
    project_id: 'project',
    scope: 'member',
    q: 'failed induction',
    status: 'FAILED',
    author: 'Ada',
    cursor: 'next',
  });
  expect(new URL(request!.url).pathname).toBe('/api/v1/discovery');
  expect(Object.fromEntries(new URL(request!.url).searchParams)).toEqual({
    project_id: 'project',
    scope: 'member',
    q: 'failed induction',
    status: 'FAILED',
    author: 'Ada',
    cursor: 'next',
  });
  expect(request!.headers.get('Authorization')).toBe('Bearer private-token');
});

it('searches exact cross-project references through public discovery', async () => {
  let request: Request | undefined;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    request = new Request(input);
    return Response.json({ items: [], next_cursor: null });
  });
  await createRecordsApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'human-token',
  }).publicSearch({ q: 'compactness', limit: 25 });

  expect(new URL(request!.url).pathname).toBe('/api/v1/discovery');
  expect(Object.fromEntries(new URL(request!.url).searchParams)).toEqual({
    q: 'compactness',
    limit: '25',
  });
  expect(request!.headers.get('Authorization')).toBe('Bearer human-token');
});

it('keeps pin history scoped and sends an exact base for explicit upgrades', async () => {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    requests.push(new Request(input));
    return new Response(JSON.stringify({ items: [], next_cursor: null }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  });
  const records = createRecordsApi({ baseUrl: 'https://api.example.test' });
  await records.references('project', 'next-page', 'reference');
  const query = new URL(requests[0]!.url).searchParams;
  expect(Object.fromEntries(query)).toEqual({
    project_id: 'project',
    cursor: 'next-page',
    reference_id: 'reference',
  });
  const body = {
    expected_current_reference_version_id: 'old-pin',
    object_version_id: 'new-revision',
    reason: 'Compare formulation',
  };
  await records.upgrade('reference', body, 'retry-key');
  expect(requests[1]!.method).toBe('POST');
  expect(new URL(requests[1]!.url).pathname).toBe('/api/v1/project-references/reference/versions');
  expect(requests[1]!.headers.get('Idempotency-Key')).toBe('retry-key');
  expect(await requests[1]!.json()).toEqual(body);
});

it('authenticates discovery when a token is supplied and uses the generated retry header for mutations', async () => {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    requests.push(new Request(input));
    return new Response(JSON.stringify({ items: [], next_cursor: null }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  });
  const options = { baseUrl: 'https://api.example.test', getAccessToken: () => 'human-token' };
  await createCatalogueApi(options).search({ q: 'failed induction' });
  await createRecordsApi(options).workPrivately({ object_version_id: 'revision' }, 'stable-key');
  expect(requests[0]?.headers.get('Authorization')).toBe('Bearer human-token');
  expect(new URL(requests[0]!.url).searchParams.get('q')).toBe('failed induction');
  expect(requests[1]?.headers.get('Authorization')).toBe('Bearer human-token');
  expect(requests[1]?.headers.get('Idempotency-Key')).toBe('stable-key');
  expect(await requests[1]?.json()).toMatchObject({
    object_version_id: 'revision',
    project_name: 'Private exploration',
  });
});

it('retains dependency cursors from the public response with supplied credentials', async () => {
  let request: Request | undefined;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    request = new Request(input);
    return new Response(JSON.stringify([]), {
      headers: { 'content-type': 'application/json', 'X-Next-Cursor': 'next-edge' },
    });
  });
  const records = createRecordsApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'private-token',
  });
  expect(await records.relationPage('exact-revision', 'previous-edge')).toEqual({
    items: [],
    next_cursor: 'next-edge',
  });
  expect(new URL(request!.url).searchParams.get('cursor')).toBe('previous-edge');
  expect(request!.headers.get('Authorization')).toBe('Bearer private-token');
});

it('expires authentication for unauthorized shared requests', async () => {
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify({ error: { code: 'unauthenticated' } }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      }),
  );
  const onUnauthorized = vi.fn();
  const options = {
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'expired-token',
    onUnauthorized,
  };

  await expect(
    createRecordsApi(options).projectSearch({ project_id: 'project' }),
  ).rejects.toMatchObject({ status: 401 });
  expect(onUnauthorized).toHaveBeenCalledTimes(1);

  await expect(createCatalogueApi(options).search()).rejects.toMatchObject({ status: 401 });
  expect(onUnauthorized).toHaveBeenCalledTimes(2);
});
