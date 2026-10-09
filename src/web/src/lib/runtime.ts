import { createApiClient, type paths } from '$lib/api-client';

export const applicationName = 'Polycolab';

/** Ensures browser code consumes the generated API-package boundary. */
export type ApiPaths = paths;

/** A server-safe factory; callers choose the deployment API origin explicitly. */
type ApiClientOptions = Parameters<typeof createApiClient>[0];

export function createWebApiClient(options: string | ApiClientOptions = {}) {
  return createApiClient({
    credentials: 'include',
    ...(typeof options === 'string' ? { baseUrl: options } : options),
  });
}
