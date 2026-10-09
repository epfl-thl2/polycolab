import type { components } from '$lib/api-client';

import { createWebApiClient } from './runtime';
import { ApiError } from './research-api';

export type AgentSession = components['schemas']['AgentSessionRead'];
export type AgentMessage = components['schemas']['AgentMessageRead'];
export type AgentRun = components['schemas']['AgentRunRead'];
export type PlatformAgent = components['schemas']['PlatformAgentRead'];
export type GatewayProfile = components['schemas']['GatewayProfileRead'];
export type AgentEvent = {
  run_id: string;
  cursor: number;
  kind: string;
  payload: Record<string, unknown>;
  occurred_at: string;
};

export type AgentSessionsApi = ReturnType<typeof createAgentSessionsApi>;

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

export function createAgentSessionsApi(
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
        client.GET('/api/v1/agent-runs/{run_id}/artifacts', {
          params: { path: { run_id: runId } },
        }),
      ),
    downloadArtifact: (runId: string, artifactId: string) =>
      unwrap(
        client.GET('/api/v1/agent-runs/{run_id}/artifacts/{artifact_id}/content', {
          params: { path: { run_id: runId, artifact_id: artifactId } },
          parseAs: 'blob',
        }),
      ),
    listAgents: () =>
      unwrapPage(client.GET('/api/v1/platform-agents', { params: { query: { limit: 25 } } })),
    listProfiles: (cursor?: string) =>
      unwrapPage(
        client.GET('/api/v1/gateway/profiles', { params: { query: { limit: 25, cursor } } }),
      ),
    listSessions: (projectId: string, cursor?: string) =>
      unwrapPage(
        client.GET('/api/v1/agent-sessions', {
          params: { query: { workspace_id: projectId, limit: 25, cursor } },
        }),
      ),
    createSession: (
      input: Omit<components['schemas']['AgentSessionCreate'], 'agent_version'> & {
        agent_version?: 1 | 2;
      },
    ) => unwrap(client.POST('/api/v1/agent-sessions', { body: { agent_version: 1, ...input } })),
    getSession: (sessionId: string) =>
      unwrap(
        client.GET('/api/v1/agent-sessions/{session_id}', {
          params: { path: { session_id: sessionId } },
        }),
      ),
    listRuns: (sessionId: string, cursor?: string) =>
      unwrapPage(
        client.GET('/api/v1/agent-sessions/{session_id}/runs', {
          params: { path: { session_id: sessionId }, query: { limit: 100, cursor } },
        }),
      ),
    listMessages: (sessionId: string, cursor?: string) =>
      unwrapPage(
        client.GET('/api/v1/agent-sessions/{session_id}/messages', {
          params: { path: { session_id: sessionId }, query: { limit: 100, cursor } },
        }),
      ),
    queueTurn: (sessionId: string, input: components['schemas']['AgentMessageCreate']) =>
      unwrap(
        client.POST('/api/v1/agent-sessions/{session_id}/messages', {
          params: { path: { session_id: sessionId } },
          body: input,
        }),
      ),
    getRun: (runId: string) =>
      unwrap(client.GET('/api/v1/agent-runs/{run_id}', { params: { path: { run_id: runId } } })),
    cancelRun: (runId: string) =>
      unwrap(
        client.POST('/api/v1/agent-runs/{run_id}/cancel', { params: { path: { run_id: runId } } }),
      ),
    resumeRun: (runId: string, input: components['schemas']['AgentRunResume']) =>
      unwrap(
        client.POST('/api/v1/agent-runs/{run_id}/resume', {
          params: { path: { run_id: runId } },
          body: input,
        }),
      ),
    stream: async function* (
      sessionId: string,
      lastEventId?: string,
      signal?: AbortSignal,
    ): AsyncGenerator<{ id: string; event: string; data: AgentEvent }> {
      const result = await client.GET('/api/v1/agent-sessions/{session_id}/events', {
        params: { path: { session_id: sessionId }, header: { 'Last-Event-ID': lastEventId } },
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
