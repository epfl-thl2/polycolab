import type { components } from '$lib/api-client';
import {
  authenticatedClient,
  result,
  type AuthenticatedClientOptions,
} from './authenticated-client';

export type DocumentBuild = components['schemas']['BuildRead'];
export type LatexEngine = components['schemas']['BuildRequest']['engine'];
const root = '/api/v1/projects/{project_id}/worktrees/{worktree_id}/latex-builds' as const;

export function createDocumentBuildsApi(options: AuthenticatedClientOptions = {}) {
  const client = authenticatedClient(options);
  return {
    list: (project_id: string, worktree_id: string) =>
      result(client.GET(root, { params: { path: { project_id, worktree_id } } })),
    create: (
      project_id: string,
      worktree_id: string,
      body: components['schemas']['BuildRequest'],
      key: string,
    ) =>
      result(
        client.POST(root, {
          params: { path: { project_id, worktree_id }, header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    cancel: (project_id: string, worktree_id: string, build_id: string) =>
      result(
        client.POST(`${root}/{build_id}/cancel`, {
          params: { path: { project_id, worktree_id, build_id } },
        }),
      ),
    output: (project_id: string, worktree_id: string, build_id: string, kind: 'pdf' | 'log') =>
      result(
        client.GET(`${root}/{build_id}/outputs/{kind}`, {
          params: { path: { project_id, worktree_id, build_id, kind } },
          parseAs: 'blob',
        }),
      ),
  };
}

/** File-line diagnostics are useful even when a full TeX log cannot be parsed. */
export function latexDiagnostics(log: string, paths: string[]) {
  const known = new Set(paths);
  return log
    .split('\n')
    .flatMap((line) => {
      const match = /^(?:\/work\/source\/|\.\/)?(.+?):(\d+):\s*(.+)$/.exec(line);
      if (!match || !known.has(match[1])) return [];
      return [{ path: match[1], line: Number(match[2]), message: match[3] }];
    })
    .slice(0, 100);
}
