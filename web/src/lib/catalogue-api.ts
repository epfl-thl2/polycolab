import type { components, paths } from '@polycolab/api-client';
import { commonsClient, result, retryHeaders, type CommonsClientOptions } from './commons-client';

export type CatalogueEntry = components['schemas']['PublicCatalogueRead'];
export type CatalogueAdmission = components['schemas']['CatalogueObjectAdmit'];
export type CatalogueRevision = components['schemas']['CatalogueVersionCreate'];
export type LibraryFilters = NonNullable<paths['/api/v1/library']['get']['parameters']['query']>;
export type DiscoveryFilters = NonNullable<
  paths['/api/v1/discovery']['get']['parameters']['query']
>;
export function createCatalogueApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    list: (cursor?: string) =>
      result(client.GET('/api/v1/catalogue', { params: { query: { cursor } } })),
    library: (query: LibraryFilters = {}) =>
      result(client.GET('/api/v1/library', { params: { query } })),
    history: (entryId: string, cursor?: string) =>
      result(
        client.GET('/api/v1/catalogue/{entry_id}/history', {
          params: { path: { entry_id: entryId }, query: { cursor } },
        }),
      ),
    revision: (entryId: string, revisionId: string) =>
      result(
        client.GET('/api/v1/catalogue/{entry_id}/versions/{object_version_id}', {
          params: { path: { entry_id: entryId, object_version_id: revisionId } },
        }),
      ),
    search: (query: DiscoveryFilters = {}) =>
      result(client.GET('/api/v1/discovery', { params: { query } })),
    get: (entryId: string) =>
      result(
        client.GET('/api/v1/catalogue/{entry_id}', {
          params: { path: { entry_id: entryId } },
        }),
      ),
    admit: (body: CatalogueAdmission, key: string) =>
      result(client.POST('/api/v1/catalogue', { body, params: { header: retryHeaders(key) } })),
    revise: (entryId: string, body: CatalogueRevision, key: string) =>
      result(
        client.POST('/api/v1/catalogue/{entry_id}/versions', {
          body,
          params: { header: retryHeaders(key), path: { entry_id: entryId } },
        }),
      ),
    promote: (body: components['schemas']['CataloguePromotionWrite'], key: string) =>
      result(
        client.POST('/api/v1/catalogue/promotions', {
          body,
          params: { header: retryHeaders(key) },
        }),
      ),
    moderate: (
      entryId: string,
      body: components['schemas']['CatalogueModerationWrite'],
      key: string,
    ) =>
      result(
        client.POST('/api/v1/catalogue/{entry_id}/moderation', {
          body,
          params: { header: retryHeaders(key), path: { entry_id: entryId } },
        }),
      ),
  };
}
