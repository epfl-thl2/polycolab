import createClient, { type Client, type ClientOptions } from 'openapi-fetch';

import type { paths } from './generated/schema';

/**
 * Callable, type-safe client generated from FastAPI's pinned OpenAPI paths.
 * Endpoint shapes remain generated in `generated/schema.ts` beside this module.
 */
export function createApiClient(options: ClientOptions = {}): Client<paths> {
  return createClient<paths>(options);
}
