import type { components } from '$lib/api-client';

import { createWebApiClient } from './runtime';
import { ApiError } from './projects-api';

export type Conversation = components['schemas']['ConversationRead'];
export type ConversationItem = components['schemas']['ItemPage']['items'][number];
export type ConversationSharing = components['schemas']['ConversationSharing'];
export type AgentRun = components['schemas']['RunRead'];
export type PlatformAgent = components['schemas']['PlatformAgentRead'];
export type ProviderConnection = components['schemas']['ProviderConnectionRead'];
export type AgentEvent = {
  run_id: string;
  cursor: number;
  kind: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

export type ConversationsApi = ReturnType<typeof createConversationsApi>;

type ErrorBody = { error?: { code?: string } };

async function unwrap<T>(
  result: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await result;
  if (data !== undefined) return data;
  throw new ApiError(
    response.status,
    (error as ErrorBody | undefined)?.error?.code ?? `request_failed_${response.status}`,
  );
}

async function unwrapPage<T>(
  result: Promise<{ data?: T[]; error?: unknown; response: Response }>,
): Promise<{ items: T[]; nextCursor?: string }> {
  const { data, error, response } = await result;
  if (data !== undefined)
    return { items: data, nextCursor: response.headers.get('X-Next-Cursor') ?? undefined };
  throw new ApiError(
    response.status,
    (error as ErrorBody | undefined)?.error?.code ?? `request_failed_${response.status}`,
  );
}

export function createConversationsApi(
  options: {
    baseUrl?: string;
    signal?: AbortSignal;
    getAccessToken?: () => string | undefined | Promise<string | undefined | null>;
    onUnauthorized?: () => void | Promise<void>;
  } = {},
) {
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
    capabilities: () => unwrap(client.GET('/api/v1/agent-capabilities')),
    listArtifacts: (runId: string) =>
      unwrap(
        client.GET('/api/v1/runs/{run_id}/artifacts', {
          params: { path: { run_id: runId } },
        }),
      ),
    downloadArtifact: (runId: string, artifactId: string) =>
      unwrap(
        client.GET('/api/v1/runs/{run_id}/artifacts/{artifact_id}/content', {
          params: { path: { run_id: runId, artifact_id: artifactId } },
          parseAs: 'blob',
        }),
      ),
    listAgents: () =>
      unwrapPage(client.GET('/api/v1/platform-agents', { params: { query: { limit: 25 } } })),
    listProfiles: (cursor?: string) =>
      unwrapPage(
        client.GET('/api/v1/account/provider-connections', {
          params: { query: { limit: 25, cursor } },
        }),
      ),
    listConversations: (projectId: string, cursor?: string) =>
      unwrapPage(
        client.GET('/api/v1/conversations', {
          params: { query: { project_id: projectId, limit: 25, cursor } },
        }),
      ),
    listHistory: (cursor?: string) =>
      unwrapPage(
        client.GET('/api/v1/conversations', {
          params: { query: { origin: 'legacy_direct', limit: 25, cursor } },
        }),
      ),
    createConversation: (
      input: Omit<components['schemas']['ConversationCreate'], 'agent_version'> & {
        agent_version?: 1 | 2 | 3;
      },
    ) => unwrap(client.POST('/api/v1/conversations', { body: { agent_version: 3, ...input } })),
    shareConversation: (conversationId: string, mode: ConversationSharing) =>
      unwrap(
        client.PATCH('/api/v1/conversations/{conversation_id}/sharing', {
          params: { path: { conversation_id: conversationId } },
          body: { mode },
        }),
      ),
    getConversation: (conversationId: string) =>
      unwrap(
        client.GET('/api/v1/conversations/{conversation_id}', {
          params: { path: { conversation_id: conversationId } },
        }),
      ),
    listRuns: (conversationId: string, cursor?: string) =>
      unwrapPage(
        client.GET('/api/v1/conversations/{conversation_id}/runs', {
          params: { path: { conversation_id: conversationId }, query: { limit: 100, cursor } },
        }),
      ),
    listItems: async (conversationId: string, cursor?: string) => {
      const page = await unwrap(
        client.GET('/api/v1/conversations/{conversation_id}/items', {
          params: { path: { conversation_id: conversationId }, query: { limit: 100, cursor } },
        }),
      );
      return { items: page.items, nextCursor: page.next_cursor ?? undefined };
    },
    updateConversation: (
      conversationId: string,
      input: components['schemas']['ConversationPatch'],
    ) =>
      unwrap(
        client.PATCH('/api/v1/conversations/{conversation_id}', {
          params: { path: { conversation_id: conversationId } },
          body: input,
        }),
      ),
    queueTurn: async (
      conversationId: string,
      input: Omit<components['schemas']['ConversationMessage'], 'type'>,
    ) => {
      const accepted = await unwrap(
        client.POST('/api/v1/conversations/{conversation_id}/events', {
          params: { path: { conversation_id: conversationId } },
          body: { ...input, type: 'message' },
        }),
      );
      if (accepted.type !== 'message')
        throw new ApiError(502, 'invalid_conversation_acknowledgement');
      return accepted;
    },
    getRun: async (runId: string): Promise<AgentRun> => {
      const run = await unwrap(
        client.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: runId } } }),
      );
      if (!('conversation_id' in run)) throw new ApiError(404, 'conversation_run_not_found');
      return run;
    },
    cancelRun: async (conversationId: string, runId: string) => {
      const accepted = await unwrap(
        client.POST('/api/v1/conversations/{conversation_id}/events', {
          params: { path: { conversation_id: conversationId } },
          body: { type: 'interrupt', run_id: runId },
        }),
      );
      return accepted.run;
    },
    resumeRun: (runId: string, input: components['schemas']['RunResume']) =>
      unwrap(
        client.POST('/api/v1/runs/{run_id}/resume', {
          params: { path: { run_id: runId } },
          body: input,
        }),
      ),
    stream: async function* (
      conversationId: string,
      lastEventId?: string,
      signal?: AbortSignal,
    ): AsyncGenerator<{ id: string; event: string; data: AgentEvent }> {
      const result = await client.GET('/api/v1/conversations/{conversation_id}/stream', {
        params: {
          path: { conversation_id: conversationId },
          header: { 'Last-Event-ID': lastEventId },
        },
        parseAs: 'stream',
        signal,
      });
      if (!result.data) throw new ApiError(result.response.status, 'event_stream_unavailable');
      const reader = result.data.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let id = '';
      let event = 'message';
      let data = '';
      try {
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines) {
            if (!line.trim()) {
              if (data) yield { id, event, data: JSON.parse(data) as AgentEvent };
              id = '';
              event = 'message';
              data = '';
            } else if (line.startsWith('id:')) id = line.slice(3).trim();
            else if (line.startsWith('event:')) event = line.slice(6).trim();
            else if (line.startsWith('data:')) data += line.slice(5).trim();
          }
        }
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
    },
  };
}
