import type { components } from './api-client';
import {
  authenticatedClient,
  result,
  retryHeaders,
  type AuthenticatedClientOptions,
} from './authenticated-client';

export type ChangeSet = components['schemas']['ChangeSetRead'];
export type CollaborativeState = components['schemas']['CollaborativeStateRead'];
export type CollaborativeFile = components['schemas']['CollaborativeFileRead'];
export type CollaborativeDocument = components['schemas']['CollaborativeDocumentRead'];
export type CollaborativeOperation = components['schemas']['CollaborativeOperationRead'];
type WireCommand = components['schemas']['CollaborativeCommand'];
export type CollaborativeCommand = Omit<WireCommand, 'binary' | 'executable'> &
  Partial<Pick<WireCommand, 'binary' | 'executable'>>;
export type CollaborativeCheckpoint = components['schemas']['CollaborativeCheckpointRead'];

export function createCollaborativeApi(options: AuthenticatedClientOptions = {}) {
  const client = authenticatedClient(options);
  const path = (project_id: string) => ({ path: { project_id } });
  return {
    changeSets: (id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/collaborative/change-sets', { params: path(id) }),
      ),
    retryChangeSet: (id: string, change_set_id: string) =>
      result(
        client.POST(
          '/api/v1/projects/{project_id}/collaborative/change-sets/{change_set_id}/retry',
          {
            params: { path: { project_id: id, change_set_id } },
          },
        ),
      ),
    revertChangeSet: (id: string, change_set_id: string) =>
      result(
        client.POST(
          '/api/v1/projects/{project_id}/collaborative/change-sets/{change_set_id}/revert',
          {
            params: { path: { project_id: id, change_set_id } },
          },
        ),
      ),
    resolveChangeSet: (
      id: string,
      change_set_id: string,
      state: CollaborativeState,
      commands: CollaborativeCommand[],
    ) =>
      result(
        client.POST(
          '/api/v1/projects/{project_id}/collaborative/change-sets/{change_set_id}/resolve',
          {
            params: {
              path: { project_id: id, change_set_id },
              header: retryHeaders(crypto.randomUUID()),
            },
            body: {
              epoch: state.epoch,
              expected_sequence: state.sequence,
              commands: commands.map((command) => ({
                binary: false,
                executable: false,
                ...command,
              })),
            },
          },
        ),
      ),
    conversionPreview: (id: string, worktree_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/collaborative/conversion-preview', {
          params: { ...path(id), query: { worktree_id } },
        }),
      ),
    convert: (id: string, worktree_id: string, revision: string, key: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/collaborative/convert', {
          params: { ...path(id), header: retryHeaders(key) },
          body: { worktree_id, revision },
        }),
      ),
    state: (id: string) =>
      result(client.GET('/api/v1/projects/{project_id}/collaborative', { params: path(id) })),
    file: (id: string, file_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/collaborative/files/{file_id}', {
          params: { path: { project_id: id, file_id } },
        }),
      ),
    change: (
      id: string,
      body: Omit<components['schemas']['CollaborativeChange'], 'commands'> & {
        commands: CollaborativeCommand[];
      },
      key = crypto.randomUUID(),
    ) =>
      result(
        client.POST('/api/v1/projects/{project_id}/collaborative/changes', {
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
        client.GET('/api/v1/projects/{project_id}/collaborative/history', {
          params: { ...path(id), query: { after } },
        }),
      ),
    checkpoints: (id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/collaborative/checkpoints', { params: path(id) }),
      ),
    checkpoint: (id: string, title: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/collaborative/checkpoints', {
          params: path(id),
          body: { id: crypto.randomUUID(), title },
        }),
      ),
    checkpointDiff: (id: string, checkpoint_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/collaborative/checkpoints/{checkpoint_id}/diff', {
          params: { path: { project_id: id, checkpoint_id } },
        }),
      ),
    checkpointFiles: (id: string, checkpoint_id: string) =>
      result(
        client.GET(
          '/api/v1/projects/{project_id}/collaborative/checkpoints/{checkpoint_id}/files',
          {
            params: { path: { project_id: id, checkpoint_id } },
          },
        ),
      ),
    restore: (id: string, checkpoint_id: string, state: CollaborativeState) =>
      result(
        client.POST('/api/v1/projects/{project_id}/collaborative/restore', {
          params: { ...path(id), header: retryHeaders(crypto.randomUUID()) },
          body: { checkpoint_id, epoch: state.epoch, sequence: state.sequence },
        }),
      ),
  };
}
