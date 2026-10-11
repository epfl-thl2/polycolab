import { afterEach, describe, expect, it, vi } from 'vitest';

import { createWebApiClient } from '../../../src/web/src/lib/runtime';

afterEach(() => vi.unstubAllGlobals());

describe('web API client', () => {
  it.each([
    { options: 'https://api.example.test', credentials: 'include' },
    { options: { baseUrl: 'https://api.example.test' }, credentials: 'include' },
    {
      options: { baseUrl: 'https://api.example.test', credentials: 'omit' as const },
      credentials: 'omit',
    },
  ])(
    'sends requests with $credentials credentials for $options',
    async ({ options, credentials }) => {
      const requests: Request[] = [];
      const payload = { agent_execution: true };
      vi.stubGlobal(
        'fetch',
        vi.fn(async (request: Request) => {
          requests.push(request);
          return Response.json(payload);
        }),
      );

      const result = await createWebApiClient(options).GET('/api/v1/config');

      expect(requests).toHaveLength(1);
      expect(requests[0]?.url).toBe('https://api.example.test/api/v1/config');
      expect(requests[0]?.credentials).toBe(credentials);
      expect(result.data).toEqual(payload);
    },
  );
});
