import type { components } from '$lib/api-client';

import { createWebApiClient } from './runtime';

export type Proposal = components['schemas']['ProposalRead'];
export type ProposalDetail = components['schemas']['ProposalDetailRead'];
export type ProposalChange = components['schemas']['ProposalChangeRead'];
export type ContextManifest = components['schemas']['ContextManifestRead'];
export type ProposalBatchDecision = components['schemas']['ProposalBatchDecision'];

export class ProposalApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string = 'request_failed',
  ) {
    super(code);
  }
}

type ErrorBody = { error?: { code?: string } };

async function unwrap<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await result;
  if (data !== undefined) return data;
  const code = (error as ErrorBody | undefined)?.error?.code ?? 'request_failed';
  throw new ProposalApiError(response.status, code);
}

async function unwrapPage<T>(
  result: Promise<{ data?: T[]; error?: unknown; response: Response }>,
): Promise<{ items: T[]; nextCursor?: string }> {
  const { data, error, response } = await result;
  if (data !== undefined) {
    return { items: data, nextCursor: response.headers.get('X-Next-Cursor') ?? undefined };
  }
  const code = (error as ErrorBody | undefined)?.error?.code ?? 'request_failed';
  throw new ProposalApiError(response.status, code);
}

export interface ProposalApi {
  listProjectProposals(
    projectId: string,
    cursor?: string,
  ): Promise<{ items: Proposal[]; nextCursor?: string }>;
  getProposal(proposalId: string): Promise<ProposalDetail>;
  getContext(proposalId: string): Promise<ContextManifest>;
  decideChanges(
    proposalId: string,
    decisions: ProposalBatchDecision[],
    idempotencyKey: string,
  ): Promise<ProposalChange[]>;
}

/** The browser-only adapter for the authenticated proposal review boundary. */
export function createProposalApi(
  options: {
    baseUrl?: string;
    signal?: AbortSignal;
    getAccessToken?: () => string | undefined | Promise<string | undefined | null>;
    onUnauthorized?: () => void | Promise<void>;
  } = {},
): ProposalApi {
  const client = createWebApiClient({
    baseUrl: options.baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? '',
  });
  client.use({
    onRequest: async ({ request }) => {
      const token = await options.getAccessToken?.();
      if (!token)
        return options.signal ? new Request(request, { signal: options.signal }) : undefined;
      const headers = new Headers(request.headers);
      headers.set('Authorization', `Bearer ${token}`);
      return new Request(request, {
        headers,
        ...(options.signal ? { signal: options.signal } : {}),
      });
    },
    onResponse: async ({ response }) => {
      if (response.status === 401) await options.onUnauthorized?.();
    },
  });

  return {
    listProjectProposals: (projectId, cursor) =>
      unwrapPage(
        client.GET('/api/v1/projects/{project_id}/proposals', {
          params: {
            path: { project_id: projectId },
            query: { limit: 25, ...(cursor ? { cursor } : {}) },
          },
        }),
      ),
    getProposal: (proposalId) =>
      unwrap(
        client.GET('/api/v1/proposals/{proposal_id}', {
          params: { path: { proposal_id: proposalId } },
        }),
      ),
    getContext: (proposalId) =>
      unwrap(
        client.GET('/api/v1/proposals/{proposal_id}/context', {
          params: { path: { proposal_id: proposalId } },
        }),
      ),
    decideChanges: (proposalId, decisions, idempotencyKey) =>
      unwrap(
        client.POST('/api/v1/proposals/{proposal_id}/decisions', {
          params: {
            path: { proposal_id: proposalId },
            header: { 'Idempotency-Key': idempotencyKey },
          },
          body: { decisions },
        }),
      ),
  };
}
