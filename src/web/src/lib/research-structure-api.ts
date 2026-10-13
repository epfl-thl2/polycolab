import type { components } from '$lib/api-client';
import { commonsClient, result, retryHeaders, type CommonsClientOptions } from './commons-client';

export type ResearchAttemptPage = components['schemas']['ObjectVersionPage'];
export type HumanNoteRead = components['schemas']['HumanNoteRead'];
export type HumanNoteWrite = components['schemas']['HumanNoteWrite'];
export type ResearchSummaryRead = components['schemas']['ResearchSummaryVersionRead'];
export type ResearchSummaryWrite = components['schemas']['ResearchSummaryVersionWrite'];
export type ResearchProgressWrite = components['schemas']['ResearchProgressVersionWrite'];
export type ResearchCommentWrite = components['schemas']['ResearchCommentVersionWrite'];
export type EndorsementWrite = components['schemas']['ObjectVersionEndorsementWrite'];
export type CorrespondenceWrite = components['schemas']['ObjectVersionCorrespondenceWrite'];
export type ObjectVersionDisplayRequest = components['schemas']['ObjectVersionDisplayRequest'];

export function createResearchStructureApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    objectVersionDisplays: (body: ObjectVersionDisplayRequest) =>
      result(
        client.POST('/api/v1/research/versions/display', {
          body,
        }),
      ),
    attempts: (
      objectId: string,
      query: {
        project_id?: string;
        target_object_version_id?: string;
        limit?: number;
        cursor?: string;
      } = {},
    ) =>
      result(
        client.GET('/api/v1/research/objects/{object_id}/attempts', {
          params: {
            path: { object_id: objectId },
            query: { ...query, scope: query.project_id ? 'member' : 'public' },
          },
        }),
      ),
    publicAttempts: (
      objectId: string,
      targetRevisionId: string,
      query: { limit?: number; cursor?: string } = {},
    ) =>
      result(
        client.GET('/api/v1/research/objects/{object_id}/attempts', {
          params: {
            path: { object_id: objectId },
            query: { target_object_version_id: targetRevisionId, ...query },
          },
        }),
      ),
    humanNote: (objectId: string, projectId?: string) =>
      result(
        client.GET('/api/v1/research/objects/{object_id}/human-note', {
          params: { path: { object_id: objectId }, query: { project_id: projectId } },
        }),
      ),
    humanNoteHistory: (
      objectId: string,
      query: { project_id?: string; limit?: number; cursor?: string } = {},
    ) =>
      result(
        client.GET('/api/v1/research/objects/{object_id}/human-note/history', {
          params: { path: { object_id: objectId }, query },
        }),
      ),
    writeHumanNote: (objectId: string, body: HumanNoteWrite, key: string) =>
      result(
        client.PUT('/api/v1/research/objects/{object_id}/human-note', {
          params: { path: { object_id: objectId }, header: retryHeaders(key) },
          body,
        }),
      ),
    summary: (objectId: string, projectId?: string) =>
      result(
        client.GET('/api/v1/research/objects/{object_id}/summary', {
          params: { path: { object_id: objectId }, query: { project_id: projectId } },
        }),
      ),
    summaryHistory: (
      objectId: string,
      query: { project_id?: string; limit?: number; cursor?: string } = {},
    ) =>
      result(
        client.GET('/api/v1/research/objects/{object_id}/summary/history', {
          params: { path: { object_id: objectId }, query },
        }),
      ),
    writeSummary: (objectId: string, body: ResearchSummaryWrite, key: string) =>
      result(
        client.PUT('/api/v1/research/objects/{object_id}/summary', {
          params: { path: { object_id: objectId }, header: retryHeaders(key) },
          body,
        }),
      ),
    progress: (
      objectId: string,
      query: {
        project_id?: string;
        object_version_id?: string;
        limit?: number;
        cursor?: string;
      } = {},
    ) =>
      result(
        client.GET('/api/v1/research/objects/{object_id}/progress', {
          params: { path: { object_id: objectId }, query },
        }),
      ),
    reportProgress: (objectId: string, body: ResearchProgressWrite, key: string) =>
      result(
        client.POST('/api/v1/research/objects/{object_id}/progress', {
          params: { path: { object_id: objectId }, header: retryHeaders(key) },
          body,
        }),
      ),
    comments: (
      objectId: string,
      query: {
        project_id?: string;
        object_version_id?: string;
        limit?: number;
        cursor?: string;
      } = {},
    ) =>
      result(
        client.GET('/api/v1/research/objects/{object_id}/comments', {
          params: { path: { object_id: objectId }, query },
        }),
      ),
    comment: (objectId: string, body: ResearchCommentWrite, key: string) =>
      result(
        client.POST('/api/v1/research/objects/{object_id}/comments', {
          params: { path: { object_id: objectId }, header: retryHeaders(key) },
          body,
        }),
      ),
    assurance: (revisionId: string, projectId: string, limit = 50, cursor?: string) =>
      result(
        client.GET('/api/v1/assurance/{object_version_id}', {
          params: {
            path: { object_version_id: revisionId },
            query: { project_id: projectId, limit, cursor },
          },
        }),
      ),
    currentAssurance: (revisionId: string, projectId: string, limit = 50, cursor?: string) =>
      result(
        client.GET('/api/v1/assurance/{object_version_id}/current', {
          params: {
            path: { object_version_id: revisionId },
            query: { project_id: projectId, limit, cursor },
          },
        }),
      ),
    publicAssurance: (revisionId: string, limit = 50, cursor?: string) =>
      result(
        client.GET('/api/v1/assurance/{object_version_id}', {
          params: { path: { object_version_id: revisionId }, query: { limit, cursor } },
        }),
      ),
    publicCurrentAssurance: (revisionId: string, limit = 50, cursor?: string) =>
      result(
        client.GET('/api/v1/assurance/{object_version_id}/current', {
          params: { path: { object_version_id: revisionId }, query: { limit, cursor } },
        }),
      ),
    endorse: (body: EndorsementWrite, key: string) =>
      result(
        client.POST('/api/v1/assurance/endorsements', {
          body,
          params: { header: retryHeaders(key) },
        }),
      ),
    assessCorrespondence: (body: CorrespondenceWrite, key: string) =>
      result(
        client.POST('/api/v1/assurance/correspondence', {
          body,
          params: { header: retryHeaders(key) },
        }),
      ),
  };
}
