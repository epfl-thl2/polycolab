import type { components } from '$lib/api-client';
import { commonsClient, result, type CommonsClientOptions } from './commons-client';

export type WorkspaceTask = components['schemas']['WorkspaceTaskRead'];

export function createWorkspaceTasksApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    list: async (workspace_id: string, cursor?: string) => {
      const response = await client.GET('/api/v1/workspaces/{workspace_id}/tasks', {
        params: { path: { workspace_id }, query: { include_archived: true, limit: 100, cursor } },
      });
      return {
        items: await result(Promise.resolve(response)),
        nextCursor: response.response.headers.get('X-Next-Cursor') ?? undefined,
      };
    },
    get: (workspace_id: string, task_id: string) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/tasks/{task_id}', {
          params: { path: { workspace_id, task_id } },
        }),
      ),
    create: (workspace_id: string, title: string, client_request_id: string) =>
      result(
        client.POST('/api/v1/workspaces/{workspace_id}/tasks', {
          params: { path: { workspace_id } },
          body: { title, client_request_id },
        }),
      ),
    update: (workspace_id: string, task_id: string, body: { title?: string; archived?: boolean }) =>
      result(
        client.PATCH('/api/v1/workspaces/{workspace_id}/tasks/{task_id}', {
          params: { path: { workspace_id, task_id } },
          body,
        }),
      ),
  };
}
