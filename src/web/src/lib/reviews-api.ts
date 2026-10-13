import type { components } from '$lib/api-client';
import { createWebApiClient } from './runtime';
import { ApiError } from './research-api';

export type Review = components['schemas']['ReviewRead'];
export type ReviewSummary = components['schemas']['ReviewSummary'];
export type ReviewWrite = components['schemas']['ReviewWrite'];
const client = createWebApiClient();

export async function listReviews(
  versionId: string,
  projectId?: string,
  cursor?: string,
  current = true,
  projectOnly = false,
) {
  const result = await client.GET('/api/v1/reviews/{object_version_id}', {
    params: {
      path: { object_version_id: versionId },
      query: { project_id: projectId, current, cursor, project_only: projectOnly },
    },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}
export async function reviewSummaries(ids: string[], projectId?: string): Promise<ReviewSummary[]> {
  if (!ids.length) return [];
  const result = await client.POST('/api/v1/reviews/summary', {
    params: { query: { project_id: projectId } },
    body: { object_version_ids: ids },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}
export async function saveReview(body: ReviewWrite, key: string) {
  const result = await client.POST('/api/v1/reviews', {
    body,
    params: { header: { 'Idempotency-Key': key } },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}
