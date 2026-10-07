import { afterEach, describe, expect, it, vi } from 'vitest';

import { createResearchApi } from '../../../web/src/lib/research-api';

const fetchBeforeTest = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = fetchBeforeTest;
});

describe('research API adapter', () => {
  it.each([false, true])('lists complete version pages (publicRead=%s)', async (publicRead) => {
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      requests.push(new Request(input));
      return Response.json({ items: [], next_cursor: 'next-version-page' });
    });
    const api = createResearchApi({ baseUrl: 'https://api.example.test' });
    await expect(
      api.listVersions('workspace', 'object', publicRead, 'previous-page'),
    ).resolves.toEqual({
      items: [],
      nextCursor: 'next-version-page',
    });
    const url = new URL(requests[0]!.url);
    expect(url.pathname).toBe('/api/v1/objects/object/versions');
    expect(url.searchParams.get('cursor')).toBe('previous-page');
  });

  it('creates a complete guarded version and then reads its object', async () => {
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = new Request(input);
      requests.push(request);
      return Response.json(
        request.method === 'POST'
          ? { outputs: [{ entity_type: 'OBJECT_VERSION', entity_id: 'version-2' }] }
          : { id: 'object', current_object_version_id: 'version-2' },
      );
    });
    const api = createResearchApi({ baseUrl: 'https://api.example.test' });
    const input = {
      expected_current_object_version_id: 'version-1',
      snapshot: {
        kind: 'STATEMENT' as const,
        content: {
          title: 'Claim',
          content_md: 'Updated',
          assumptions_md: 'None',
          reported_outcome: null,
          explanation_md: null,
        },
        structural_relationships: [],
        change_summary: null,
      },
    };
    await expect(api.createVersion('object', input)).resolves.toMatchObject({
      current_object_version_id: 'version-2',
    });
    expect(new URL(requests[0]!.url).pathname).toBe('/api/v1/objects/object/versions');
    expect(await requests[0]!.json()).toEqual(input);
    expect(requests[0]!.headers.get('Idempotency-Key')).toBeTruthy();
    expect(new URL(requests[1]!.url).pathname).toBe('/api/v1/objects/object');
  });

  it('uses the refreshed bearer token for member calls and preserves page cursors', async () => {
    let token = 'first-token';
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = new Request(input);
      requests.push(request);
      return Response.json({ items: [], next_cursor: 'opaque-next' });
    });
    const api = createResearchApi({
      baseUrl: 'https://api.example.test',
      getAccessToken: () => token,
    });
    token = 'refreshed-token';

    const page = await api.listProjects();

    expect(requests[0]?.headers.get('Authorization')).toBe('Bearer refreshed-token');
    expect(page).toEqual({ items: [], nextCursor: 'opaque-next' });
  });

  it('adds members by exact username while preserving the UUID compatibility boundary', async () => {
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init);
      requests.push(request);
      return new Response(
        JSON.stringify({
          user_id: '11111111-1111-4111-8111-111111111111',
          username: 'grace.hopper',
          display_name: 'Grace Hopper',
          role: 'CONTRIBUTOR',
          created_at: '2026-09-09T10:00:00Z',
        }),
        { status: 201, headers: { 'content-type': 'application/json' } },
      );
    });
    const api = createResearchApi({ baseUrl: 'https://api.example.test' });

    await api.addMember('project-a', { username: 'grace.hopper', role: 'CONTRIBUTOR' });
    await api.addMember('project-a', {
      user_id: '11111111-1111-4111-8111-111111111111',
      role: 'READ_ONLY',
    });

    expect(await requests[0]!.json()).toEqual({
      username: 'grace.hopper',
      role: 'CONTRIBUTOR',
    });
    expect(await requests[1]!.json()).toEqual({
      user_id: '11111111-1111-4111-8111-111111111111',
      role: 'READ_ONLY',
    });
  });

  it('uses the generated anonymous public-workspace route without leaking a human token', async () => {
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const request = new Request(input);
      requests.push(request);
      return new Response(
        JSON.stringify({
          id: 'project',
          name: 'Public',
          description: null,
          visibility: 'PUBLIC',
          archived_at: null,
          created_at: '2026-09-09T10:00:00Z',
          updated_at: '2026-09-09T10:00:00Z',
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    });
    const api = createResearchApi({
      baseUrl: 'https://api.example.test',
      getAccessToken: () => 'not-for-public',
    });

    await expect(api.getPublicProject('project')).resolves.toMatchObject({ name: 'Public' });
    expect(new URL(requests[0]!.url).pathname).toBe('/api/v1/workspaces/project');
    expect(requests[0]!.headers.get('Authorization')).toBe('Bearer not-for-public');
  });

  it('accepts generated void mutations with a successful 204 response', async () => {
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      requests.push(new Request(input));
      return new Response(null, { status: 204 });
    });
    const api = createResearchApi({
      baseUrl: 'https://api.example.test',
      getAccessToken: () => 'owner-token',
    });

    await expect(api.deleteGatewayProfile('profile-a')).resolves.toBeUndefined();
    expect(requests[0]?.method).toBe('DELETE');
    expect(new URL(requests[0]!.url).pathname).toBe('/api/v1/gateway/profiles/profile-a');
  });

  it('notifies the auth boundary when a member request is unauthorized', async () => {
    globalThis.fetch = vi.fn(
      async () =>
        new Response(JSON.stringify({ error: { code: 'unauthenticated' } }), {
          status: 401,
          headers: { 'content-type': 'application/json' },
        }),
    );
    const onUnauthorized = vi.fn();
    const api = createResearchApi({
      baseUrl: 'https://api.example.test',
      getAccessToken: () => 'expired-token',
      onUnauthorized,
    });

    await expect(api.listProjects()).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });
});
