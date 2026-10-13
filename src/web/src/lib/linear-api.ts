import type { components } from './api-client';
import { commonsClient, result, retryHeaders, type CommonsClientOptions } from './commons-client';

export type LinearBatch = components['schemas']['BatchRead'];
export type LinearState = components['schemas']['LinearStateRead'];
export type LinearFile = components['schemas']['LinearFileRead'];
export type LinearDocument = components['schemas']['LinearDocumentRead'];
export type LinearOperation = components['schemas']['LinearOperationRead'];
type WireCommand = components['schemas']['LinearCommand'];
export type LinearCommand = Omit<WireCommand, 'binary' | 'executable'> &
  Partial<Pick<WireCommand, 'binary' | 'executable'>>;
export type LinearCheckpoint = components['schemas']['LinearCheckpointRead'];

export function createLinearApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  const path = (project_id: string) => ({ path: { project_id } });
  return {
    batches: (id: string) =>
      result(client.GET('/api/v1/projects/{project_id}/linear/batches', { params: path(id) })),
    retryBatch: (id: string, batch_id: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/linear/batches/{batch_id}/retry', {
          params: { path: { project_id: id, batch_id } },
        }),
      ),
    revertBatch: (id: string, batch_id: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/linear/batches/{batch_id}/revert', {
          params: { path: { project_id: id, batch_id } },
        }),
      ),
    resolveBatch: (id: string, batch_id: string, state: LinearState, commands: LinearCommand[]) =>
      result(
        client.POST('/api/v1/projects/{project_id}/linear/batches/{batch_id}/resolve', {
          params: { path: { project_id: id, batch_id }, header: retryHeaders(crypto.randomUUID()) },
          body: {
            epoch: state.epoch,
            expected_sequence: state.sequence,
            commands: commands.map((command) => ({ binary: false, executable: false, ...command })),
          },
        }),
      ),
    conversionPreview: (id: string, worktree_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/linear/conversion-preview', {
          params: { ...path(id), query: { worktree_id } },
        }),
      ),
    convert: (id: string, worktree_id: string, revision: string, key: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/linear/convert', {
          params: { ...path(id), header: retryHeaders(key) },
          body: { worktree_id, revision },
        }),
      ),
    state: (id: string) =>
      result(client.GET('/api/v1/projects/{project_id}/linear', { params: path(id) })),
    file: (id: string, file_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/linear/files/{file_id}', {
          params: { path: { project_id: id, file_id } },
        }),
      ),
    change: (
      id: string,
      body: Omit<components['schemas']['LinearChange'], 'commands'> & { commands: LinearCommand[] },
      key = crypto.randomUUID(),
    ) =>
      result(
        client.POST('/api/v1/projects/{project_id}/linear/changes', {
          params: { ...path(id), header: retryHeaders(key) },
          body: {
            ...body,
            commands: body.commands.map((command) => ({
              binary: false,
              executable: false,
              ...command,
            })),
          },
        }),
      ),
    history: (id: string, after = 0) =>
      result(
        client.GET('/api/v1/projects/{project_id}/linear/history', {
          params: { ...path(id), query: { after } },
        }),
      ),
    checkpoints: (id: string) =>
      result(client.GET('/api/v1/projects/{project_id}/linear/checkpoints', { params: path(id) })),
    checkpoint: (id: string, title: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/linear/checkpoints', {
          params: path(id),
          body: { id: crypto.randomUUID(), title },
        }),
      ),
    checkpointDiff: (id: string, checkpoint_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/linear/checkpoints/{checkpoint_id}/diff', {
          params: { path: { project_id: id, checkpoint_id } },
        }),
      ),
    checkpointFiles: (id: string, checkpoint_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/linear/checkpoints/{checkpoint_id}/files', {
          params: { path: { project_id: id, checkpoint_id } },
        }),
      ),
    restore: (id: string, checkpoint_id: string, state: LinearState) =>
      result(
        client.POST('/api/v1/projects/{project_id}/linear/restore', {
          params: { ...path(id), header: retryHeaders(crypto.randomUUID()) },
          body: { checkpoint_id, epoch: state.epoch, sequence: state.sequence },
        }),
      ),
  };
}
