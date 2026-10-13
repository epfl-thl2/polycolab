<script lang="ts">
  import type { Snippet } from 'svelte';
  import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
  import '../styles/project.css';
  const client = new QueryClient({
    queryCache: new QueryCache({
      onError(error, query) {
        if ([401, 403, 404].includes((error as { status?: number }).status ?? 0)) {
          query.setState({ data: undefined, dataUpdatedAt: 0 });
        }
      },
    }),
    defaultOptions: {
      queries: { retry: false, staleTime: 15_000, gcTime: 300_000, refetchOnWindowFocus: true },
      mutations: { retry: false },
    },
  });
  let { children }: { children: Snippet } = $props();
</script>

<QueryClientProvider {client}>{@render children()}</QueryClientProvider>
