import type { components } from '$lib/api-client';
import { commonsClient, result, type CommonsClientOptions } from './commons-client';

export type ProjectTask = components['schemas']['ProjectTaskRead'] &
  Partial<components['schemas']['WorktreeRead']>;

export function createProjectTasksApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
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
    get: (project_id: string, task_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/worktrees/{worktree_id}', {
          params: { path: { project_id, worktree_id: task_id } },
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
    update: async (
      project_id: string,
      task_id: string,
      body: { title?: string; archived?: boolean; discard_changes?: boolean },
    ) => {
      const path = { project_id, worktree_id: task_id };
      if (body.archived === false)
        return result(
          client.POST('/api/v1/projects/{project_id}/worktrees/{worktree_id}/restore', {
            params: { path },
          }),
        );
      const tree = await result(
        client.GET('/api/v1/projects/{project_id}/worktrees/{worktree_id}', {
          params: { path },
        }),
      );
      return result(
        client.POST('/api/v1/projects/{project_id}/worktrees/{worktree_id}/remove', {
          params: { path, header: { 'Idempotency-Key': crypto.randomUUID() } },
          body: {
            expected_revision: tree.revision!,
            discard_changes: body.discard_changes ?? false,
          },
        }),
      );
    },
  };
}
