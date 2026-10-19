import { createInfiniteQuery, type InfiniteData, type QueryClient } from '@tanstack/svelte-query';
import { readable, toStore } from 'svelte/store';
import type { AgentSession, AgentSessionsApi } from './agent-sessions-api';

type SessionPage = Awaited<ReturnType<AgentSessionsApi['listSessions']>>;
export const sessionKeys = {
  list: (projectId: string) => ['sessions', projectId] as const,
  detail: (sessionId: string | undefined) => ['session', sessionId] as const,
};

export function createProjectSessions(
  api: AgentSessionsApi,
  projectId: () => string,
  enabled: () => boolean = () => true,
  queryClient?: QueryClient,
  poll = true,
) {
  return createInfiniteQuery(
    toStore(() => {
      const id = projectId();
      const readable = enabled();
      return {
        queryKey: sessionKeys.list(id),
        enabled: readable,
        initialPageParam: undefined as string | undefined,
        queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
          api.listSessions(id, pageParam),
        getNextPageParam: (page: SessionPage) => page.nextCursor,
        staleTime: 5000,
        refetchInterval: readable && poll ? 5000 : (false as const),
      };
    }),
    queryClient,
  );
}

export function projectSessionItems(data: InfiniteData<SessionPage> | undefined) {
  return [
    ...new Map(
      (data?.pages.flatMap((page) => page.items) ?? []).map((session) => [session.id, session]),
    ).values(),
  ];
}

export function sessionOptions(
  api: AgentSessionsApi,
  sessionId: string | undefined,
  active = true,
) {
  return {
    queryKey: sessionKeys.detail(sessionId),
    enabled: Boolean(sessionId),
    queryFn: () => api.getSession(sessionId!),
    staleTime: 5000,
    refetchInterval: active && sessionId ? 5000 : (false as const),
  };
}

export function invalidateSession(query: QueryClient, projectId: string, sessionId?: string) {
  return Promise.all([
    query.invalidateQueries({ queryKey: sessionKeys.list(projectId) }),
    ...(sessionId ? [query.invalidateQueries({ queryKey: sessionKeys.detail(sessionId) })] : []),
  ]);
}

// A read-only projection of the cache, never another writable copy of session state.
export function sessionTitles(query: QueryClient, projectId: string) {
  const read = () => {
    const entries = new Map<string, AgentSession>();
    const pages = query.getQueryData<InfiniteData<SessionPage>>(sessionKeys.list(projectId));
    for (const page of pages?.pages ?? [])
      for (const session of page.items) entries.set(session.id, session);
    for (const [, session] of query.getQueriesData<AgentSession>({ queryKey: ['session'] })) {
      if (!session || session.project_id !== projectId) continue;
      const summary = entries.get(session.id);
      if (!summary || session.updated_at >= summary.updated_at) entries.set(session.id, session);
    }
    return Object.fromEntries(
      [...entries].map(([id, session]) => [
        id,
        session.title?.trim() || session.agent_display_name || 'Chat',
      ]),
    );
  };
  return readable<Record<string, string>>({}, (set) => {
    let previous = '';
    const update = () => {
      const titles = read();
      const signature = JSON.stringify(titles);
      if (signature !== previous) {
        previous = signature;
        set(titles);
      }
    };
    update();
    return query.getQueryCache().subscribe((event) => {
      if (event.type !== 'updated' && event.type !== 'removed' && event.type !== 'added') return;
      const [kind, id] = event.query.queryKey;
      if (kind === 'session' || (kind === 'sessions' && id === projectId)) update();
    });
  });
}
