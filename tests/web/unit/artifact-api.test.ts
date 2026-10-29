import { afterEach, expect, it, vi } from 'vitest';
import { createArtifactApi } from '../../../src/web/src/lib/artifact-api';

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

it('uploads verified project bytes and downloads with current authentication', async () => {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init);
    requests.push(request.clone());
    if (request.url.endsWith('/content')) return new Response('evidence');
    return Response.json({ id: 'artifact-a', state: 'COMMITTED' });
  });
  const api = createArtifactApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'token',
  });
  const artifact = await api.upload(
    'project-a',
    new File(['evidence'], 'result.txt', { type: 'text/plain' }),
  );
  expect(artifact.state).toBe('COMMITTED');
  const content = await api.download('project-a', artifact.id);
  expect(content.size).toBe(8);
  expect(requests.map((r) => new URL(r.url).pathname)).toEqual([
    '/api/v1/projects/project-a/artifacts',
    '/api/v1/projects/project-a/artifacts/artifact-a/content',
  ]);
  expect(Object.fromEntries(new URL(requests[0]!.url).searchParams)).toEqual({
    sha256: 'ee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e',
    byte_length: '8',
    media_type: 'text/plain',
  });
  expect(await requests[0]!.text()).toBe('evidence');
  expect(requests.every((r) => r.headers.get('Authorization') === 'Bearer token')).toBe(true);
});
