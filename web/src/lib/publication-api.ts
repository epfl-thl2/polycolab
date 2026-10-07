import type { components } from '@polycolab/api-client';
import { commonsClient, result, retryHeaders, type CommonsClientOptions } from './commons-client';

export type PublicationVersionSelection = components['schemas']['PublicationVersionSelection'];
export type PublicationVersionConfirm = components['schemas']['PublicationVersionConfirm'];

export function createPublicationApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    preview: (body: PublicationVersionSelection) =>
      result(client.POST('/api/v1/publication/preview', { body })),
    confirm: (body: PublicationVersionConfirm, key: string) =>
      result(
        client.POST('/api/v1/publication/confirm', {
          body,
          params: { header: retryHeaders(key) },
        }),
      ),
    history: (projectId: string, limit = 25, cursor?: string) =>
      result(
        client.GET('/api/v1/publication/history', {
          params: { query: { workspace_id: projectId, limit, cursor } },
        }),
      ),
    publicManifest: (manifestId: string) =>
      result(
        client.GET('/api/v1/publications/{manifest_id}', {
          params: { path: { manifest_id: manifestId } },
        }),
      ),
  };
}
