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
        paths['/api/v1/projects/{project_id}/verification-environments']['get']['parameters']['query']
      > = {},
    ) =>
      result(
        client.GET('/api/v1/projects/{project_id}/verification-environments', {
          params: { path: { project_id: projectId }, query },
        }),
      ),
    submit: (projectId: string, submission: VerificationJobSubmission, retryKey: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/verification-jobs', {
          params: { path: { project_id: projectId } },
          body: { submission, retry_key: retryKey },
        }),
      ),
    inspect: (projectId: string, jobId: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/verification-jobs/{job_id}', {
          params: { path: { project_id: projectId, job_id: jobId } },
        }),
      ),
    events: (projectId: string, jobId: string, afterSequence = 0, limit = 100) =>
      result(
        client.GET('/api/v1/projects/{project_id}/verification-jobs/{job_id}/events', {
          params: {
            path: { project_id: projectId, job_id: jobId },
            query: { after_sequence: afterSequence, limit },
          },
        }),
      ),
    cancel: (projectId: string, jobId: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/verification-jobs/{job_id}/cancel', {
          params: { path: { project_id: projectId, job_id: jobId } },
        }),
      ),
    rerun: (projectId: string, jobId: string, retryKey: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/verification-jobs/{job_id}/rerun', {
          params: { path: { project_id: projectId, job_id: jobId } },
          body: { retry_key: retryKey },
        }),
      ),
  };
}
