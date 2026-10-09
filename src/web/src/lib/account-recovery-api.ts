import type { components } from '$lib/api-client';

import { ApiError } from './research-api';
import { createWebApiClient } from './runtime';

export type AccountEmail = components['schemas']['AccountEmailRead'];
type RecoveryAccepted = components['schemas']['RecoveryAccepted'];
type ErrorBody = { error?: { code?: string } };

async function unwrap<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await result;
  if (response.ok) return data as T;
  const code = (error as ErrorBody | undefined)?.error?.code ?? 'request_failed';
  throw new ApiError(response.status, code);
}

export function createAccountRecoveryApi(
  options: {
    baseUrl?: string;
    getAccessToken?: () => string | undefined | Promise<string | undefined | null>;
    onUnauthorized?: () => void | Promise<void>;
  } = {},
) {
  const client = createWebApiClient({
    baseUrl: options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? '',
  });
  client.use({
    onRequest: async ({ request }) => {
      const token = await options.getAccessToken?.();
      if (!token) return;
      const headers = new Headers(request.headers);
      headers.set('Authorization', `Bearer ${token}`);
      return new Request(request, { headers });
    },
    onResponse: async ({ response }) => {
      if (response.status === 401) await options.onUnauthorized?.();
    },
  });

  return {
    email: () => unwrap(client.GET('/api/v1/account/email')),
    changeEmail: (email: string) =>
      unwrap(client.PUT('/api/v1/account/email', { body: { email } })),
    resendVerification: () => unwrap<RecoveryAccepted>(client.POST('/api/v1/account/email/resend')),
    verifyEmail: (token: string) =>
      unwrap<RecoveryAccepted>(client.POST('/api/v1/account/email/verify', { body: { token } })),
    requestPasswordReset: (email: string) =>
      unwrap<RecoveryAccepted>(
        client.POST('/api/v1/auth/password-reset/request', { body: { email } }),
      ),
    confirmPasswordReset: (token: string, password: string) =>
      unwrap<RecoveryAccepted>(
        client.POST('/api/v1/auth/password-reset/confirm', {
          body: { token, password },
        }),
      ),
  };
}
