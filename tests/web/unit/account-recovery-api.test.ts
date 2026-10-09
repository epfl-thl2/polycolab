import { afterEach, describe, expect, it, vi } from 'vitest';

import { createAccountRecoveryApi } from '../../../src/web/src/lib/account-recovery-api';

const fetchBeforeTest = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = fetchBeforeTest;
});

describe('account recovery API adapter', () => {
  it('uses only generated recovery operations and keeps tokens in request bodies', async () => {
    const requests: Request[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init);
      requests.push(request);
      const path = new URL(request.url).pathname;
      return new Response(
        JSON.stringify(
          path === '/api/v1/account/email'
            ? {
                verified_email: null,
                verified_at: null,
                pending_email: 'ada@example.test',
                pending_requested_at: '2026-09-09T10:00:00Z',
              }
            : { accepted: true },
        ),
        { status: 200, headers: { 'content-type': 'application/json' } },
      );
    });
    const recovery = createAccountRecoveryApi({ baseUrl: 'https://api.example.test' });

    await recovery.email();
    await recovery.changeEmail('ada@example.test');
    await recovery.resendVerification();
    await recovery.verifyEmail('verification-secret');
    await recovery.requestPasswordReset('ada@example.test');
    await recovery.confirmPasswordReset('reset-secret', 'a secure new password');

    expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
      '/api/v1/account/email',
      '/api/v1/account/email',
      '/api/v1/account/email/resend',
      '/api/v1/account/email/verify',
      '/api/v1/auth/password-reset/request',
      '/api/v1/auth/password-reset/confirm',
    ]);
    expect(await requests[3]!.json()).toEqual({ token: 'verification-secret' });
    expect(await requests[5]!.json()).toEqual({
      token: 'reset-secret',
      password: 'a secure new password',
    });
    expect(requests[3]!.url).not.toContain('verification-secret');
    expect(requests[5]!.url).not.toContain('reset-secret');
  });
});
