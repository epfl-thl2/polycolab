import type { components, paths } from '@polycolab/api-client';
import { commonsClient, result, retryHeaders, type CommonsClientOptions } from './commons-client';

export type RecordRead = import('./research-api').ObjectVersion;
export type ScopedRelationWrite = import('./research-api').RelationshipCreate;
export function createRecordsApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    create: (body: components['schemas']['VersionedObjectCreate'], key: string) =>
      result(client.POST('/api/v1/objects', { body, params: { header: retryHeaders(key) } })),
    workspaceSearch: (
      query: NonNullable<paths['/api/v1/discovery']['get']['parameters']['query']>,
    ) =>
      result(client.GET('/api/v1/discovery', { params: { query: { ...query, scope: 'member' } } })),
    publicSearch: (query: NonNullable<paths['/api/v1/discovery']['get']['parameters']['query']>) =>
      result(client.GET('/api/v1/discovery', { params: { query } })),
    workspaceList: (query: NonNullable<paths['/api/v1/records']['get']['parameters']['query']>) =>
      result(client.GET('/api/v1/records', { params: { query: { ...query, scope: 'member' } } })),
    workspaceGet: (projectId: string, revisionId: string) =>
      result(
        client.GET('/api/v1/records/{object_version_id}', {
          params: { path: { object_version_id: revisionId }, query: { workspace_id: projectId } },
        }),
      ),
    list: (query: NonNullable<paths['/api/v1/records']['get']['parameters']['query']>) =>
      result(client.GET('/api/v1/records', { params: { query } })),
    get: (revisionId: string) =>
      result(
        client.GET('/api/v1/records/{object_version_id}', {
          params: { path: { object_version_id: revisionId } },
        }),
      ),
    moderate: (
      objectId: string,
      body: components['schemas']['RecordModerationWrite'],
      key: string,
    ) =>
      result(
        client.POST('/api/v1/records/objects/{object_id}/moderation', {
          body,
          params: { path: { object_id: objectId }, header: retryHeaders(key) },
        }),
      ),
    relations: (revisionId: string) =>
      result(
        client.GET('/api/v1/versions/{object_version_id}/relationships', {
          params: { path: { object_version_id: revisionId } },
        }),
      ),
    relationPage: async (revisionId: string, cursor?: string, projectId?: string) => {
      const response = projectId
        ? await client.GET('/api/v1/versions/{object_version_id}/relationships', {
            params: {
              path: { object_version_id: revisionId },
              query: { workspace_id: projectId, cursor },
            },
          })
        : await client.GET('/api/v1/versions/{object_version_id}/relationships', {
            params: { path: { object_version_id: revisionId }, query: { cursor } },
          });
      return {
        items: await result(Promise.resolve(response)),
        next_cursor: response.response.headers.get('X-Next-Cursor'),
      };
    },
    relate: (body: ScopedRelationWrite, key: string) =>
      result(client.POST('/api/v1/relations', { body, params: { header: retryHeaders(key) } })),
    copyToWorkspace: (body: components['schemas']['WorkspaceVersionCopyCreate'], key: string) =>
      result(
        client.POST('/api/v1/workspace-copies', { body, params: { header: retryHeaders(key) } }),
      ),
    importToWorkspace: (body: components['schemas']['WorkspaceReferenceCreate'], key: string) =>
      result(
        client.POST('/api/v1/workspace-references', {
          body,
          params: { header: retryHeaders(key) },
        }),
      ),
    workPrivately: (
      body: Pick<
        components['schemas']['WorkspaceReferenceCreate'],
        'object_version_id' | 'workspace_id'
      >,
      key: string,
    ) =>
      result(
        client.POST('/api/v1/workspace-references', {
          body: {
            workspace_name: 'Private exploration',
            reason: 'Work privately',
            workspace_visibility: 'PRIVATE',
            ...body,
          },
          params: { header: retryHeaders(key) },
        }),
      ),
    references: (projectId: string, cursor?: string, referenceId?: string) =>
      result(
        client.GET('/api/v1/workspace-references', {
          params: { query: { workspace_id: projectId, cursor, reference_id: referenceId } },
        }),
      ),
    upgrade: (
      referenceId: string,
      body: components['schemas']['WorkspaceReferenceUpgrade'],
      key: string,
    ) =>
      result(
        client.POST('/api/v1/workspace-references/{reference_id}/versions', {
          body,
          params: { header: retryHeaders(key), path: { reference_id: referenceId } },
        }),
      ),
    decide: (
      objectVersionId: string,
      body: components['schemas']['CorrectionDecisionWrite'],
      key: string,
    ) =>
      result(
        client.POST('/api/v1/records/{object_version_id}/decision', {
          body,
          params: { header: retryHeaders(key), path: { object_version_id: objectVersionId } },
        }),
      ),
    decision: (objectVersionId: string) =>
      result(
        client.GET('/api/v1/records/{object_version_id}/decision', {
          params: { path: { object_version_id: objectVersionId } },
        }),
      ),
  };
}
