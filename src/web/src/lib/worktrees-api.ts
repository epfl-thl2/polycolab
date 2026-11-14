import type { components } from '$lib/api-client';
import {
  authenticatedClient,
  result,
  type AuthenticatedClientOptions,
} from './authenticated-client';

export type Worktree = components['schemas']['WorktreeRead'];

export function createWorktreesApi(options: AuthenticatedClientOptions = {}) {
  const client = authenticatedClient(options);
  return {
    list: async (project_id: string, _cursor?: string) => {
      void _cursor;
      const response = await client.GET('/api/v1/projects/{project_id}/worktrees', {
        params: { path: { project_id }, query: { include_removed: true } },
      });
      return {
        items: await result(Promise.resolve(response)),
        nextCursor: response.response.headers.get('X-Next-Cursor') ?? undefined,
      };
    },
    get: (project_id: string, worktree_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/worktrees/{worktree_id}', {
          params: { path: { project_id, worktree_id } },
        }),
      ),
    create: (
      project_id: string,
      title: string,
      client_request_id: string,
      branch?: string,
      start_branch = 'main',
    ) =>
      result(
        client.POST('/api/v1/projects/{project_id}/worktrees', {
          params: { path: { project_id } },
          body: {
            title,
            client_request_id,
            branch:
              branch ||
              title
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/^-|-$/g, ''),
            start_branch,
          },
        }),
      ),
    update: (project_id: string, worktree_id: string, title: string) =>
      result(
        client.PATCH('/api/v1/projects/{project_id}/worktrees/{worktree_id}', {
          params: { path: { project_id, worktree_id } },
          body: { title },
        }),
      ),
    restore: (project_id: string, worktree_id: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/worktrees/{worktree_id}/restore', {
          params: { path: { project_id, worktree_id } },
        }),
      ),
    remove: (
      project_id: string,
      worktree_id: string,
      expected_revision: string,
      discard_changes = false,
      idempotency_key = crypto.randomUUID(),
    ) =>
      result(
        client.POST('/api/v1/projects/{project_id}/worktrees/{worktree_id}/remove', {
          params: {
            path: { project_id, worktree_id },
            header: { 'Idempotency-Key': idempotency_key },
          },
          body: { expected_revision, discard_changes },
        }),
      ),
  };
}
