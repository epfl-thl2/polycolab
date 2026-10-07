import { describe, expect, it } from 'vitest';

import { applicationName, createWebApiClient } from '../../../web/src/lib/runtime';

describe('web foundation', () => {
  it('identifies the application', () => {
    expect(applicationName).toBe('Polycolab');
  });

  it('uses the generated API client package boundary', () => {
    expect(createWebApiClient('https://api.example.test').GET).toBeTypeOf('function');
  });
});
