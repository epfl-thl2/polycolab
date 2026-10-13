import type { components } from '$lib/api-client';
import { commonsClient, result, type CommonsClientOptions } from './commons-client';

export type RepositoryState = components['schemas']['RepositoryState'] & {
  head_commit?: string;
  worktree_id?: string;
  changed_files?: components['schemas']['WorktreeChange'][];
  ignored_files?: string[];
};
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
  const revisions = new Map<string, string>();
  async function state(project_id: string, branch = 'main'): Promise<RepositoryState> {
    const legacy = await result(
      client.GET('/api/v1/projects/{project_id}/repository', {
        params: { path: { project_id }, query: { branch } },
      }),
    );
    if (!legacy.enabled) return legacy;
    const trees = await result(
      client.GET('/api/v1/projects/{project_id}/worktrees', {
        params: { path: { project_id } },
      }),
    );
    const tree = trees.find((item) => item.branch === branch);
    if (!tree || tree.lifecycle !== 'active' || !tree.revision)
      throw new Error('This worktree is unavailable.');
    revisions.set(tree.revision, tree.id);
    return {
      ...legacy,
      commit: tree.revision,
      head_commit: tree.head_commit,
      worktree_id: tree.id,
      files: tree.files,
      writable: tree.writable,
      changed_files: tree.changed_files,
      ignored_files: tree.ignored_files,
    };
  }
  return {
    session: (project_id: string, session_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/repository/sessions/{session_id}', {
          params: { path: { project_id, session_id } },
        }),
      ),
    enableSession: (project_id: string, session_id: string) =>
      result(
        client.PUT('/api/v1/projects/{project_id}/repository/sessions/{session_id}', {
          params: { path: { project_id, session_id } },
        }),
      ),
    run: (project_id: string, run_id: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/repository/runs/{run_id}', {
          params: { path: { project_id, run_id } },
        }),
      ),
    state,
    file: (project_id: string, commit: string, path: string) => {
      const worktree_id = revisions.get(commit);
      return worktree_id
        ? result(
            client.GET('/api/v1/projects/{project_id}/worktrees/{worktree_id}/file', {
              params: { path: { project_id, worktree_id }, query: { revision: commit, path } },
            }),
          )
        : result(
            client.GET('/api/v1/projects/{project_id}/repository/file', {
              params: { path: { project_id }, query: { commit, path } },
            }),
          );
    },
    history: (project_id: string, branch: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/repository/history', {
          params: { path: { project_id }, query: { branch } },
        }),
      ),
    diff: (project_id: string, base: string, target: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/repository/diff', {
          params: { path: { project_id }, query: { base, target } },
        }),
      ),
    save: async (project_id: string, body: RepositorySave, key: string) => {
      const worktree_id = revisions.get(body.expected_commit);
      if (!worktree_id) throw new Error('Refresh this worktree before saving.');
      const saved = await result(
        client.POST('/api/v1/projects/{project_id}/worktrees/{worktree_id}/save', {
          params: { path: { project_id, worktree_id }, header: { 'Idempotency-Key': key } },
          body: { expected_revision: body.expected_commit, changes: body.changes },
        }),
      );
      revisions.set(saved.revision, worktree_id);
      return { commit: saved.revision };
    },
    changes: (project_id: string, worktree_id: string, revision: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/worktrees/{worktree_id}/diff', {
          params: { path: { project_id, worktree_id }, query: { revision } },
        }),
      ),
    commit: (
      project_id: string,
      worktree_id: string,
      expected_revision: string,
      message: string,
      key: string,
    ) =>
      result(
        client.POST('/api/v1/projects/{project_id}/worktrees/{worktree_id}/commit', {
          params: { path: { project_id, worktree_id }, header: { 'Idempotency-Key': key } },
          body: { expected_revision, message },
        }),
      ),
    discard: (project_id: string, worktree_id: string, expected_revision: string, key: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/worktrees/{worktree_id}/discard', {
          params: { path: { project_id, worktree_id }, header: { 'Idempotency-Key': key } },
          body: { expected_revision },
        }),
      ),
    preview: (project_id: string, target: string, source: string) =>
      result(
        client.GET('/api/v1/projects/{project_id}/repository/merge', {
          params: { path: { project_id }, query: { target, source } },
        }),
      ),
    merge: (project_id: string, body: RepositoryMerge, key: string) =>
      result(
        client.POST('/api/v1/projects/{project_id}/repository/merge', {
          params: { path: { project_id }, header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
  };
}
