import type { components } from '$lib/api-client';

import { createWebApiClient } from './runtime';
import { ApiError, type Page } from './research-api';

export type ExternalCredential = components['schemas']['ExternalCredentialRead'];
export type IssuedExternalCredential = components['schemas']['ExternalCredentialIssued'];
export type AgentIdentity = components['schemas']['AgentIdentityRead'];
export type ProjectRun = components['schemas']['ProjectRunRead'];

type ErrorBody = { error?: { code?: string } };

async function unwrap<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await result;
  if (response.ok) return data as T;
  throw new ApiError(
    response.status,
    (error as ErrorBody | undefined)?.error?.code ?? 'request_failed',
  );
}

async function page<T>(
  result: Promise<{
    data?: { items: T[]; next_cursor?: string | null };
    error?: unknown;
    response: Response;
  }>,
): Promise<Page<T>> {
  const { data, error, response } = await result;
  if (response.ok) return { items: data?.items ?? [], nextCursor: data?.next_cursor ?? undefined };
  throw new ApiError(
    response.status,
    (error as ErrorBody | undefined)?.error?.code ?? 'request_failed',
  );
}

export function createExternalAgentApi(
  options: {
    baseUrl?: string;
    getAccessToken?: () => string | undefined | Promise<string | undefined | null>;
    onUnauthorized?: () => void | Promise<void>;
  } = {},
) {
  const clientOptions = { baseUrl: options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? '' };
  const human = createWebApiClient(clientOptions);
  human.use({
    onRequest: async ({ request }) => {
      const token = await options.getAccessToken?.();
      if (!token) return;
      const headers = new Headers(request.headers);
      headers.set('Authorization', `Bearer ${token}`);
      return new Request(request, { headers });
    },
    onResponse: async ({ response }) => {
      if (response.status === 401) await options.onUnauthorized?.();
    },
  });
  const query = (cursor?: string) => ({ limit: 25, ...(cursor ? { cursor } : {}) });

  return {
    listAgents: (cursor?: string) =>
      page(human.GET('/api/v1/account/agents', { params: { query: query(cursor) } })),
    createAgent: (name: string) => unwrap(human.POST('/api/v1/account/agents', { body: { name } })),
    renameAgent: (agentId: string, name: string) =>
      unwrap(
        human.PATCH('/api/v1/account/agents/{agent_id}', {
          params: { path: { agent_id: agentId } },
          body: { name },
        }),
      ),
    identity: () => unwrap(human.GET('/api/v1/me')),
    listCredentials: (cursor?: string) =>
      page(
        human.GET('/api/v1/account/agent-keys', {
          params: { query: query(cursor) },
        }),
      ),
    createCredential: (
      name: string,
      agentId: string,
      allowLibraryContributions = false,
      allowReviews = false,
    ) =>
      unwrap(
        human.POST('/api/v1/account/agent-keys', {
          body: {
            name,
            agent_id: agentId,
            allow_library_contributions: allowLibraryContributions,
            allow_reviews: allowReviews,
          },
        }),
      ),
    revealCredential: (credentialId: string) =>
      unwrap(
        human.POST('/api/v1/account/agent-keys/{credential_id}/reveal', {
          params: { path: { credential_id: credentialId } },
        }),
      ),
    revokeCredential: (credentialId: string) =>
      unwrap<void>(
        human.DELETE('/api/v1/account/agent-keys/{credential_id}', {
          params: { path: { credential_id: credentialId } },
        }),
      ),
    listProjectRuns: (projectId: string, cursor?: string) =>
      page(
        human.GET('/api/v1/projects/{project_id}/runs', {
          params: { path: { project_id: projectId }, query: query(cursor) },
        }),
      ),
  };
}
