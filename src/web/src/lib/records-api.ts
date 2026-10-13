import type { components, paths } from '$lib/api-client';
import { commonsClient, result, retryHeaders, type CommonsClientOptions } from './commons-client';

export type RecordRead = import('./research-api').ObjectVersion;
export type ScopedRelationWrite = import('./research-api').RelationshipCreate;
export function createRecordsApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    create: (body: components['schemas']['VersionedObjectCreate'], key: string) =>
      result(client.POST('/api/v1/objects', { body, params: { header: retryHeaders(key) } })),
    projectSearch: (query: NonNullable<paths['/api/v1/discovery']['get']['parameters']['query']>) =>
      result(client.GET('/api/v1/discovery', { params: { query: { ...query, scope: 'member' } } })),
    publicSearch: (query: NonNullable<paths['/api/v1/discovery']['get']['parameters']['query']>) =>
      result(client.GET('/api/v1/discovery', { params: { query } })),
    projectList: (query: NonNullable<paths['/api/v1/records']['get']['parameters']['query']>) =>
      result(client.GET('/api/v1/records', { params: { query: { ...query, scope: 'member' } } })),
    projectGet: (projectId: string, revisionId: string) =>
      result(
        client.GET('/api/v1/records/{object_version_id}', {
          params: { path: { object_version_id: revisionId }, query: { project_id: projectId } },
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
              query: { project_id: projectId, cursor },
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
    copyToProject: (body: components['schemas']['ProjectVersionCopyCreate'], key: string) =>
      result(
        client.POST('/api/v1/project-copies', { body, params: { header: retryHeaders(key) } }),
      ),
    importToProject: (body: components['schemas']['ProjectReferenceCreate'], key: string) =>
      result(
        client.POST('/api/v1/project-references', {
          body,
          params: { header: retryHeaders(key) },
        }),
      ),
    workPrivately: (
      body: Pick<
        components['schemas']['ProjectReferenceCreate'],
        'object_version_id' | 'project_id'
      >,
      key: string,
    ) =>
      result(
        client.POST('/api/v1/project-references', {
          body: {
            project_name: 'Private exploration',
            reason: 'Work privately',
            project_visibility: 'PRIVATE',
            ...body,
          },
          params: { header: retryHeaders(key) },
        }),
      ),
    references: (projectId: string, cursor?: string, referenceId?: string) =>
      result(
        client.GET('/api/v1/project-references', {
          params: { query: { project_id: projectId, cursor, reference_id: referenceId } },
        }),
      ),
    upgrade: (
      referenceId: string,
      body: components['schemas']['ProjectReferenceUpgrade'],
      key: string,
    ) =>
      result(
        client.POST('/api/v1/project-references/{reference_id}/versions', {
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
