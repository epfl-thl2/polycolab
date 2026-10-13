import type { components } from '$lib/api-client';
import { createWebApiClient } from './runtime';
import { ApiError } from './research-api';
import type { createExternalAgentApi } from './external-agent-api';

export type LibraryKind = components['schemas']['LibraryCreate']['kind'];
export type LibraryContent = components['schemas']['LibraryContentWrite'];
export type LibraryOwned = components['schemas']['LibraryOwnedRead'];
export type LibraryPublic = components['schemas']['LibraryPublicRead'];
export type LibraryVersion = components['schemas']['LibraryVersionRead'];
export type LibraryFilters = { kind?: LibraryKind; q?: string; tag?: string; cursor?: string };

async function unwrap<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await result;
  if (response.ok) return data as T;
  const body = error as { detail?: unknown; error?: { code?: string } } | undefined;
  throw new ApiError(
    response.status,
    typeof body?.detail === 'string' ? body.detail : (body?.error?.code ?? 'request_failed'),
  );
}

export function createAgentLibraryApi(options: Parameters<typeof createExternalAgentApi>[0] = {}) {
  const client = createWebApiClient({
    baseUrl: options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? '',
  });
  client.use({
    onRequest: async ({ request }) => {
      const token = await options.getAccessToken?.();
      if (token) request.headers.set('Authorization', `Bearer ${token}`);
      return request;
    },
    onResponse: async ({ response }) => {
      if (response.status === 401) await options.onUnauthorized?.();
    },
  });
  const path = (entryId: string) => ({ entry_id: entryId });
  const headers = (key: string) => ({ 'Idempotency-Key': key });
  return {
    list: (filters: LibraryFilters = {}) =>
      unwrap(client.GET('/api/v1/agent-library', { params: { query: { limit: 25, ...filters } } })),
    yours: (filters: LibraryFilters = {}) =>
      unwrap(
        client.GET('/api/v1/agent-library/yours', { params: { query: { limit: 25, ...filters } } }),
      ),
    get: (entryId: string, versionId?: string) =>
      versionId
        ? unwrap(
            client.GET('/api/v1/agent-library/{entry_id}/versions/{version_id}', {
              params: { path: { ...path(entryId), version_id: versionId } },
            }),
          )
        : unwrap(
            client.GET('/api/v1/agent-library/{entry_id}', { params: { path: path(entryId) } }),
          ),
    history: (entryId: string, cursor?: string) =>
      unwrap(
        client.GET('/api/v1/agent-library/{entry_id}/versions', {
          params: { path: path(entryId), query: { limit: 25, cursor } },
        }),
      ),
    draft: (entryId: string) =>
      unwrap(
        client.GET('/api/v1/agent-library/{entry_id}/draft', { params: { path: path(entryId) } }),
      ),
    create: (kind: LibraryKind, content: LibraryContent, key: string) =>
      unwrap(
        client.POST('/api/v1/agent-library', {
          body: { kind, content },
          params: { header: headers(key) },
        }),
      ),
    update: (entryId: string, content: LibraryContent, revision: number, key: string) =>
      unwrap(
        client.PUT('/api/v1/agent-library/{entry_id}/draft', {
          params: { path: path(entryId), header: headers(key) },
          body: { content, expected_revision: revision },
        }),
      ),
    publish: (entryId: string, revision: number, key: string) =>
      unwrap(
        client.POST('/api/v1/agent-library/{entry_id}/publish', {
          params: { path: path(entryId), header: headers(key) },
          body: { expected_revision: revision },
        }),
      ),
    copy: (entryId: string, versionId: string, key: string) =>
      unwrap(
        client.POST('/api/v1/agent-library/{entry_id}/copy', {
          params: { path: path(entryId), header: headers(key) },
          body: { version_id: versionId },
        }),
      ),
    archive: (entryId: string, revision: number, archived: boolean, key: string) =>
      unwrap(
        client.POST('/api/v1/agent-library/{entry_id}/archive', {
          params: { path: path(entryId), header: headers(key) },
          body: { expected_revision: revision, archived },
        }),
      ),
    moderationState: (entryId: string) =>
      unwrap(
        client.GET('/api/v1/agent-library/{entry_id}/moderation', {
          params: { path: path(entryId) },
        }),
      ),
    moderate: (entryId: string, revision: number, hidden: boolean, reason: string, key: string) =>
      unwrap(
        client.POST('/api/v1/agent-library/{entry_id}/moderation', {
          params: { path: path(entryId), header: headers(key) },
          body: { expected_revision: revision, hidden, reason },
        }),
      ),
    downloadHref: (entryId: string, versionId: string) =>
      `${options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? ''}/api/v1/agent-library/${encodeURIComponent(entryId)}/versions/${encodeURIComponent(versionId)}/SKILL.md`,
  };
}
export type AgentLibraryApi = ReturnType<typeof createAgentLibraryApi>;

export function libraryError(error: unknown): string {
  const code = (error as { code?: string }).code;
  if (code === 'agent_library_stale_revision' || code === 'agent_library_conflict')
    return 'This entry changed or this retry conflicts with an earlier action. Your inputs are retained. Reload the saved draft before trying again.';
  if (code === 'skill_frontmatter_required' || code === 'skill_frontmatter_invalid')
    return 'SKILL.md needs valid YAML frontmatter with a lowercase, hyphenated name and a description. YAML aliases are not supported.';
  if (code === 'publication_license_required') return 'Choose a license before publishing.';
  if (code === 'agent_library_archived')
    return 'This entry is archived. Restore it before editing, publishing, or making a copy.';
  if (code === 'agent_library_moderation_denied')
    return 'Only configured library moderators can hide or restore entries.';
  if (code === 'plugin_source_runtime_instructions_required')
    return 'A plugin listing needs a source URL, target runtime, and setup instructions.';
  if ((error as { status?: number }).status === 404)
    return 'This entry is unavailable or you do not have access.';
  if ((error as { status?: number }).status === 422)
    return 'Check the required fields, field lengths, and source URL before retrying.';
  if ((error as { status?: number }).status === 401) return 'Sign in to continue.';
  return 'Could not complete this request. Your inputs are retained; try again.';
}
