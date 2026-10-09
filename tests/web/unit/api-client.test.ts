import { describe, expect, it } from 'vitest';

import { createApiClient } from '../../../src/web/src/lib/api-client';

describe('generated API client boundary', () => {
  it('creates a callable client over generated paths', () => {
    const client = createApiClient({ baseUrl: 'https://api.example.test' });

    expect(client.GET).toBeTypeOf('function');
    expect(client.POST).toBeTypeOf('function');
  });
});
