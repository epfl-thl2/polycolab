import { afterEach, expect, it, vi } from 'vitest';

import {
  createVerificationApi,
  type VerificationJobSubmission,
} from '../../../src/web/src/lib/verification-api';

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const submission: VerificationJobSubmission = {
  version: 1,
  project_id: 'project-a',
  work_target_object_version_id: 'target-r2',
  research_attempt_object_version_id: 'attempt-r1',
  environment_id: 'environment-a',
  purpose: 'LEAN_CHECK',
  evidence_scope: 'Checks the exact statement under the recorded assumptions.',
  inputs: [{ path: 'Main.lean', role: 'SOURCE', object_version_id: 'source-r3' }],
  entrypoint: 'Main.lean',
  arguments: [],
  seed: null,
  limits: {
    cpu_count: 1,
    cpu_seconds: 30,
    wall_seconds: 60,
    memory_bytes: 268_435_456,
    process_count: 8,
    disk_bytes: 268_435_456,
    output_bytes: 1_048_576,
    log_bytes: 1_048_576,
    output_files: 8,
  },
};

it('submits the exact generated verification manifest with its retry identity', async () => {
  let request: Request | undefined;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    request = new Request(input, init);
    return new Response(JSON.stringify({ id: 'job-a' }), {
      status: 201,
      headers: { 'content-type': 'application/json' },
    });
  });
  const api = createVerificationApi({
    baseUrl: 'https://api.example.test',
    getAccessToken: () => 'member-token',
  });

  await api.submit('project-a', submission, 'stable-retry');

  expect(request?.method).toBe('POST');
  expect(new URL(request!.url).pathname).toBe('/api/v1/projects/project-a/verification-jobs');
  expect(request?.headers.get('Authorization')).toBe('Bearer member-token');
  expect(await request?.json()).toEqual({ submission, retry_key: 'stable-retry' });
});

it('discovers a bounded page of exact curated environments', async () => {
  let request: Request | undefined;
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    request = new Request(input, init);
    return new Response(JSON.stringify({ items: [], next_after: null }), {
      headers: { 'content-type': 'application/json' },
    });
  });
  const api = createVerificationApi({ baseUrl: 'https://api.example.test' });

  await api.environments('project-a', { language: 'LEAN', limit: 50, after: 'environment-a' });

  expect(request?.method).toBe('GET');
  expect(new URL(request!.url).pathname).toBe(
    '/api/v1/projects/project-a/verification-environments',
  );
  expect(Object.fromEntries(new URL(request!.url).searchParams)).toEqual({
    after: 'environment-a',
    language: 'LEAN',
    limit: '50',
  });
});

it('uses bounded committed-event replay and canonical control endpoints', async () => {
  const requests: Request[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init);
    requests.push(request);
    const body = request.url.includes('/events') ? [] : { id: 'job-a' };
    return new Response(JSON.stringify(body), {
      status: request.url.endsWith('/rerun') ? 201 : 200,
      headers: { 'content-type': 'application/json' },
    });
  });
  const api = createVerificationApi({ baseUrl: 'https://api.example.test' });

  await api.inspect('project-a', 'job-a');
  await api.events('project-a', 'job-a', 17, 250);
  await api.cancel('project-a', 'job-a');
  await api.rerun('project-a', 'job-a', 'rerun-key');

  expect(requests.map((request) => `${request.method} ${new URL(request.url).pathname}`)).toEqual([
    'GET /api/v1/projects/project-a/verification-jobs/job-a',
    'GET /api/v1/projects/project-a/verification-jobs/job-a/events',
    'POST /api/v1/projects/project-a/verification-jobs/job-a/cancel',
    'POST /api/v1/projects/project-a/verification-jobs/job-a/rerun',
  ]);
  expect(Object.fromEntries(new URL(requests[1]!.url).searchParams)).toEqual({
    after_sequence: '17',
    limit: '250',
  });
  expect(await requests[3]!.json()).toEqual({ retry_key: 'rerun-key' });
});

it('preserves normalized quota errors and expires unauthorized sessions', async () => {
  let status = 429;
  globalThis.fetch = vi.fn(
    async () =>
      new Response(JSON.stringify({ error: { code: 'verification_quota_exceeded' } }), {
        status,
        headers: { 'content-type': 'application/json' },
      }),
  );
  const onUnauthorized = vi.fn();
  const api = createVerificationApi({ baseUrl: 'https://api.example.test', onUnauthorized });

  await expect(api.submit('project-a', submission, 'retry')).rejects.toMatchObject({
    status: 429,
    code: 'verification_quota_exceeded',
  });
  expect(onUnauthorized).not.toHaveBeenCalled();

  status = 401;
  await expect(api.inspect('project-a', 'job-a')).rejects.toMatchObject({ status: 401 });
  expect(onUnauthorized).toHaveBeenCalledOnce();
});
