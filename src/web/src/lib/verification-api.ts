import type { components, paths } from '$lib/api-client';

import { commonsClient, result, type CommonsClientOptions } from './commons-client';

export type VerificationJobRead = components['schemas']['VersionJobRead'];
export type VerificationJobSubmission = components['schemas']['VersionJobSubmission'];
export type VerificationEventRead = components['schemas']['EventRead'];
export type VerificationEnvironmentRead = components['schemas']['VerificationEnvironmentRead'];
export type VerificationEnvironmentPage = components['schemas']['VerificationEnvironmentPage'];

export function createVerificationApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    environments: (
      projectId: string,
      query: NonNullable<
        paths['/api/v1/workspaces/{workspace_id}/verification-environments']['get']['parameters']['query']
      > = {},
    ) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/verification-environments', {
          params: { path: { workspace_id: projectId }, query },
        }),
      ),
    submit: (projectId: string, submission: VerificationJobSubmission, retryKey: string) =>
      result(
        client.POST('/api/v1/workspaces/{workspace_id}/verification-jobs', {
          params: { path: { workspace_id: projectId } },
          body: { submission, retry_key: retryKey },
        }),
      ),
    inspect: (projectId: string, jobId: string) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/verification-jobs/{job_id}', {
          params: { path: { workspace_id: projectId, job_id: jobId } },
        }),
      ),
    events: (projectId: string, jobId: string, afterSequence = 0, limit = 100) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/verification-jobs/{job_id}/events', {
          params: {
            path: { workspace_id: projectId, job_id: jobId },
            query: { after_sequence: afterSequence, limit },
          },
        }),
      ),
    cancel: (projectId: string, jobId: string) =>
      result(
        client.POST('/api/v1/workspaces/{workspace_id}/verification-jobs/{job_id}/cancel', {
          params: { path: { workspace_id: projectId, job_id: jobId } },
        }),
      ),
    rerun: (projectId: string, jobId: string, retryKey: string) =>
      result(
        client.POST('/api/v1/workspaces/{workspace_id}/verification-jobs/{job_id}/rerun', {
          params: { path: { workspace_id: projectId, job_id: jobId } },
          body: { retry_key: retryKey },
        }),
      ),
  };
}
