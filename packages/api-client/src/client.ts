import createClient, { type Client, type ClientOptions } from 'openapi-fetch';

import type { paths } from './generated/schema';

/**
 * Callable, type-safe client generated from FastAPI's pinned OpenAPI paths.
 * Endpoint shapes remain generated in `src/generated/schema.ts`.
 */
export function createApiClient(options: ClientOptions = {}): Client<paths> {
  return createClient<paths>(options);
}
