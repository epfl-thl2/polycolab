import { createInfiniteQuery, type InfiniteData, type QueryClient } from '@tanstack/svelte-query';
import { readable, toStore } from 'svelte/store';
import type { Conversation, ConversationsApi } from './conversations-api';

type ConversationPage = Awaited<ReturnType<ConversationsApi['listConversations']>>;
export const conversationKeys = {
  list: (projectId: string) => ['conversations', projectId] as const,
  detail: (conversationId: string | undefined) => ['conversation', conversationId] as const,
};

export function createProjectConversations(
  api: ConversationsApi,
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
        queryKey: conversationKeys.list(id),
        enabled: readable,
        initialPageParam: undefined as string | undefined,
        queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
          api.listConversations(id, pageParam),
        getNextPageParam: (page: ConversationPage) => page.nextCursor,
        staleTime: 5000,
        refetchInterval: readable && poll ? 5000 : (false as const),
      };
    }),
    queryClient,
  );
}

export function projectConversationItems(data: InfiniteData<ConversationPage> | undefined) {
  return [
    ...new Map(
      (data?.pages.flatMap((page) => page.items) ?? []).map((conversation) => [
        conversation.id,
        conversation,
      ]),
    ).values(),
  ];
}

export function conversationOptions(
  api: ConversationsApi,
  conversationId: string | undefined,
  active = true,
) {
  return {
    queryKey: conversationKeys.detail(conversationId),
    enabled: Boolean(conversationId),
    queryFn: () => api.getConversation(conversationId!),
    staleTime: 5000,
    refetchInterval: active && conversationId ? 5000 : (false as const),
  };
}

export function invalidateConversation(
  query: QueryClient,
  projectId: string,
  conversationId?: string,
) {
  return Promise.all([
    query.invalidateQueries({ queryKey: conversationKeys.list(projectId) }),
    ...(conversationId
      ? [query.invalidateQueries({ queryKey: conversationKeys.detail(conversationId) })]
      : []),
  ]);
}

// A read-only projection of the cache, never another writable copy of conversation state.
export function conversationTitles(query: QueryClient, projectId: string) {
  const read = () => {
    const entries = new Map<string, Conversation>();
    const pages = query.getQueryData<InfiniteData<ConversationPage>>(
      conversationKeys.list(projectId),
    );
    for (const page of pages?.pages ?? [])
      for (const conversation of page.items) entries.set(conversation.id, conversation);
    for (const [, conversation] of query.getQueriesData<Conversation>({
      queryKey: ['conversation'],
    })) {
      if (!conversation || conversation.project_id !== projectId) continue;
      const summary = entries.get(conversation.id);
      if (!summary || conversation.updated_at >= summary.updated_at)
        entries.set(conversation.id, conversation);
    }
    return Object.fromEntries(
      [...entries].map(([id, conversation]) => [
        id,
        conversation.title?.trim() || conversation.configuration?.display_name || 'Chat',
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
      if (kind === 'conversation' || (kind === 'conversations' && id === projectId)) update();
    });
  });
}
