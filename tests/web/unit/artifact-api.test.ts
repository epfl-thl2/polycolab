import { afterEach, expect, it, vi } from 'vitest';
import { createArtifactApi } from '../../../src/web/src/lib/artifact-api';

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

it('uploads declared raw bytes, commits an exact attachment, and downloads as a blob', async () => {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init);
    requests.push(request.clone());
    const path = new URL(request.url).pathname;
    if (path.endsWith('/attachments')) return Response.json({ id: 'attachment-a' });
    if (path.endsWith('/content'))
      return new Response('stored evidence', {
        headers: { 'content-type': 'application/octet-stream' },
      });
    return Response.json({
      id: 'artifact-a',
      sha256: 'ab',
      byte_length: 8,
      media_type: 'text/plain',
      state: path.endsWith('/artifact-a') ? 'COMMITTED' : 'STAGING',
      expires_at: '2026-09-08T00:00:00Z',
    });
  });
  const api = createArtifactApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'owner-token',
  });
  const file = new File(['evidence'], 'result.txt', { type: 'text/plain' });

  const artifact = await api.uploadAndAttach('project-a', {
    file,
    role: 'EVIDENCE',
    researchRevisionId: 'proof-r2',
    researchAttemptRevisionId: 'attempt-r1',
  });
  const content = await api.download('project-a', 'artifact-a');

  expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
    '/api/v1/artifacts',
    '/api/v1/attachments',
    '/api/v1/artifacts/artifact-a',
    '/api/v1/artifacts/artifact-a/content',
  ]);
  expect(requests[0]!.headers.get('Content-Type')).toBe('application/octet-stream');
  expect(await requests[0]!.text()).toBe('evidence');
  expect(Object.fromEntries(new URL(requests[0]!.url).searchParams)).toEqual({
    sha256: 'ee8250fb76e094b34b471f13a73dbbe51d1ae142e9df59d7c0d31ec20f0a0a8e',
    byte_length: '8',
    media_type: 'text/plain',
    source_object_version_id: 'proof-r2',
    project_id: 'project-a',
  });
  expect(await requests[1]!.json()).toEqual({
    artifact_id: 'artifact-a',
    object_version_id: 'proof-r2',
    attempt_object_version_id: 'attempt-r1',
    role: 'EVIDENCE',
  });
  expect(
    requests.every((request) => request.headers.get('Authorization') === 'Bearer owner-token'),
  ).toBe(true);
  expect(artifact.state).toBe('COMMITTED');
  expect(content).toBeInstanceOf(Blob);
  expect(content.size).toBe(15);
});

it('pages committed artifact attachments for one exact research version', async () => {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(new Request(input, init));
    return Response.json({ items: [], next_cursor: null });
  });
  const api = createArtifactApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'reader-token',
  });

  await api.attachments('project-a', {
    object_version_id: 'proof-r2',
    limit: 25,
    cursor: 'attachment-next',
  });

  expect(new URL(requests[0]!.url).pathname).toBe('/api/v1/projects/project-a/artifacts');
  expect(Object.fromEntries(new URL(requests[0]!.url).searchParams)).toEqual({
    object_version_id: 'proof-r2',
    limit: '25',
    cursor: 'attachment-next',
  });
  expect(requests[0]!.headers.get('Authorization')).toBe('Bearer reader-token');
});

it('discovers and downloads committed public evidence anonymously after reload', async () => {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init);
    requests.push(request);
    return request.url.endsWith('/content')
      ? new Response('public evidence')
      : Response.json({ items: [], next_cursor: null });
  });
  const api = createArtifactApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'human-token',
  });

  await api.publicAttachments('project-a', { object_version_id: 'proof-r2', limit: 25 });
  await api.publicDownload('artifact-a');

  expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
    '/api/v1/projects/project-a/artifacts',
    '/api/v1/artifacts/artifact-a/content',
  ]);
  expect(requests.every((request) => request.headers.get('Authorization') === null)).toBe(true);
});
