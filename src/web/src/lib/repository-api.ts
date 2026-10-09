import type { components } from '$lib/api-client';
import { commonsClient, result, type CommonsClientOptions } from './commons-client';

export type RepositoryState = components['schemas']['RepositoryState'];
export type RepositoryCommit = components['schemas']['RepositoryCommit'];
export type RepositoryMergePreview = components['schemas']['RepositoryMergePreview'];
export type RepositorySave = components['schemas']['RepositorySave'];
export type RepositoryMerge = components['schemas']['RepositoryMerge'];

export function encodeFile(value: string): string {
  return bytesToBase64(new TextEncoder().encode(value));
}
export function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 8192)
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(binary);
}
export function decodeFile(value: string): string {
  return new TextDecoder('utf-8', { fatal: true }).decode(
    Uint8Array.from(atob(value), (c) => c.charCodeAt(0)),
  );
}
export function createRepositoryApi(options: CommonsClientOptions = {}) {
  const client = commonsClient(options);
  return {
    session: (workspace_id: string, session_id: string) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/repository/sessions/{session_id}', {
          params: { path: { workspace_id, session_id } },
        }),
      ),
    enableSession: (workspace_id: string, session_id: string) =>
      result(
        client.PUT('/api/v1/workspaces/{workspace_id}/repository/sessions/{session_id}', {
          params: { path: { workspace_id, session_id } },
        }),
      ),
    run: (workspace_id: string, run_id: string) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/repository/runs/{run_id}', {
          params: { path: { workspace_id, run_id } },
        }),
      ),
    state: (workspace_id: string, branch = 'main') =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/repository', {
          params: { path: { workspace_id }, query: { branch } },
        }),
      ),
    file: (workspace_id: string, commit: string, path: string) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/repository/file', {
          params: { path: { workspace_id }, query: { commit, path } },
        }),
      ),
    history: (workspace_id: string, branch: string) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/repository/history', {
          params: { path: { workspace_id }, query: { branch } },
        }),
      ),
    diff: (workspace_id: string, base: string, target: string) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/repository/diff', {
          params: { path: { workspace_id }, query: { base, target } },
        }),
      ),
    save: (workspace_id: string, body: RepositorySave, key: string) =>
      result(
        client.POST('/api/v1/workspaces/{workspace_id}/repository/changes', {
          params: { path: { workspace_id }, header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    preview: (workspace_id: string, target: string, source: string) =>
      result(
        client.GET('/api/v1/workspaces/{workspace_id}/repository/merge', {
          params: { path: { workspace_id }, query: { target, source } },
        }),
      ),
    merge: (workspace_id: string, body: RepositoryMerge, key: string) =>
      result(
        client.POST('/api/v1/workspaces/{workspace_id}/repository/merge', {
          params: { path: { workspace_id }, header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
  };
}
