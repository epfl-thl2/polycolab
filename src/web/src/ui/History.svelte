<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { Button } from '../lib/components/ui/button';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery } from '@tanstack/svelte-query';
  import { workspace, explain } from '../svelte-lib/context';
  import type { ObjectVersion } from '../lib/research-api';
  let {
    projectId,
    objectId,
    onselect,
  }: { projectId: string; objectId: string; onselect: (version: ObjectVersion) => void } = $props();
  const { api } = workspace();
  const history = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['history', projectId, objectId],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        api.listVersions(projectId, objectId, false, pageParam),
      getNextPageParam: (page: { nextCursor?: string }) => page.nextCursor,
    })),
  );
</script>

<h2>Version history</h2>
{#if $history.isPending}<LoadingState>Loading history…</LoadingState
  >{:else if $history.isError}<Alert.Root variant="destructive" role="alert">
    {explain($history.error)}
  </Alert.Root>
  <Button type="submit" onclick={() => $history.refetch()}>Retry</Button>{:else}<ul class="list">
    {#each $history.data?.pages.flatMap((p) => p.items) ?? [] as revision (revision.id)}<li>
        <Button type="submit" variant="outline" class="" onclick={() => onselect(revision)}
          >Read version {revision.number}</Button
        >
        <small
          >{revision.authorship.actor_kind === 'AGENT'
            ? (revision.authorship.agent_display_name ?? 'Research agent')
            : (revision.authorship.author_display_name ?? 'Member')} · {new Date(
            revision.created_at,
          ).toLocaleString()}</small
        >
      </li>{/each}
  </ul>{/if}{#if $history.hasNextPage}<Button
    type="submit"
    disabled={$history.isFetchingNextPage}
    onclick={() => $history.fetchNextPage()}>Load more history</Button
  >{/if}
