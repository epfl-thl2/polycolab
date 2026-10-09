import { createWebApiClient } from './runtime';
import { ApiError } from './research-api';

export type CommonsClientOptions = {
  baseUrl?: string;
  getAccessToken?: () => string | undefined | null | Promise<string | undefined | null>;
  onUnauthorized?: () => void | Promise<void>;
};

export function commonsClient(options: CommonsClientOptions = {}) {
  const client = createWebApiClient({
    baseUrl: options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? '',
  });
  client.use({
    onRequest: async ({ request }) => {
      const token = await options.getAccessToken?.();
      if (token) request.headers.set('Authorization', `Bearer ${token}`);
      return request;
    },
    onResponse: async ({ response }) => {
      if (response.status === 401) await options.onUnauthorized?.();
    },
  });
  return client;
}

export async function result<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await request;
  if (error || !response.ok) {
    const code =
      typeof error === 'object' &&
      error !== null &&
      'error' in error &&
      typeof error.error === 'object' &&
      error.error !== null &&
      'code' in error.error &&
      typeof error.error.code === 'string'
        ? error.error.code
        : 'request_failed';
    throw new ApiError(response.status, code);
  }
  return data as T;
}

export const retryHeaders = (key: string) => ({ 'Idempotency-Key': key });
