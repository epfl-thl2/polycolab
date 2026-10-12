import type { components } from '$lib/api-client';
import { commonsClient, result, type CommonsClientOptions } from './commons-client';

export type WorkspaceTask = components['schemas']['WorkspaceTaskRead'] &
  Partial<components['schemas']['WorktreeRead']>;

export function createWorkspaceTasksApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    list: async (workspace_id: string, _cursor?: string) => {
      void _cursor;
      const response = await client.GET('/api/v1/workspaces/{workspace_id}/worktrees', {
        params: { path: { workspace_id }, query: { include_removed: true } },
      });
      return {
        items: await result(Promise.resolve(response)),
        nextCursor: response.response.headers.get('X-Next-Cursor') ?? undefined,
      };
    },
    get: (workspace_id: string, task_id: string) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/worktrees/{worktree_id}', {
          params: { path: { workspace_id, worktree_id: task_id } },
        }),
      ),
    create: (
      workspace_id: string,
      title: string,
      client_request_id: string,
      branch?: string,
      start_branch = 'main',
    ) =>
      result(
        client.POST('/api/v1/workspaces/{workspace_id}/worktrees', {
          params: { path: { workspace_id } },
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
      workspace_id: string,
      task_id: string,
      body: { title?: string; archived?: boolean; discard_changes?: boolean },
    ) => {
      const path = { workspace_id, worktree_id: task_id };
      if (body.archived === false)
        return result(
          client.POST('/api/v1/workspaces/{workspace_id}/worktrees/{worktree_id}/restore', {
            params: { path },
          }),
        );
      const tree = await result(
        client.GET('/api/v1/workspaces/{workspace_id}/worktrees/{worktree_id}', {
          params: { path },
        }),
      );
      return result(
        client.POST('/api/v1/workspaces/{workspace_id}/worktrees/{worktree_id}/remove', {
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
