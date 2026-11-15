<script lang="ts">
  import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import { projectContext, explain } from '../svelte-lib/context';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import * as Field from '../lib/components/ui/field';
  import FeedbackToast from './FeedbackToast.svelte';
  import LoadingState from './LoadingState.svelte';
  import ConversationTranscriptItem from '../pages/project/components/ConversationTranscriptItem.svelte';

  let { conversationId }: { conversationId?: string } = $props();
  const { agents, query } = projectContext();
  const history = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['conversation-history'],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) => agents.listHistory(pageParam),
      getNextPageParam: (page: { nextCursor?: string }) => page.nextCursor,
    })),
  );
  const conversation = createQuery(
    toStore(() => ({
      queryKey: ['conversation', conversationId],
      enabled: Boolean(conversationId),
      queryFn: () => agents.getConversation(conversationId!),
    })),
  );
  const items = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['conversation-items', conversationId],
      enabled: Boolean(conversationId && $conversation.data?.origin === 'legacy_direct'),
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        agents.listItems(conversationId!, pageParam),
      getNextPageParam: (page: { nextCursor?: string }) => page.nextCursor,
    })),
  );
  const runs = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['conversation-runs', conversationId],
      enabled: Boolean(conversationId && $conversation.data?.origin === 'legacy_direct'),
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        agents.listRuns(conversationId!, pageParam),
      getNextPageParam: (page: { nextCursor?: string }) => page.nextCursor,
    })),
  );
  let error = $state('');
  let title = $state('');
  let editing = $state(false);
  async function update(input: { title?: string | null; archived?: boolean }) {
    if (!conversationId) return;
    try {
      await agents.updateConversation(conversationId, input);
      editing = false;
      await Promise.all([
        query.invalidateQueries({ queryKey: ['conversation-history'] }),
        query.invalidateQueries({ queryKey: ['conversation', conversationId] }),
      ]);
    } catch (reason) {
      error = explain(reason);
    }
  }
</script>

<section class="settings-content" aria-labelledby="history-title">
  <h2 id="history-title">Saved chat history</h2>
  <p>Retired direct-chat conversations are read-only. You can read, rename, or archive them.</p>
  <FeedbackToast
    message={error || ($history.error ? explain($history.error) : '')}
    variant="error"
  />
  {#if $history.isPending}<LoadingState>Loading history…</LoadingState>{/if}
  <nav aria-label="Saved conversations">
    {#each $history.data?.pages.flatMap((page) => page.items) ?? [] as saved (saved.id)}
      <a
        href={`/settings/conversation-history/${saved.id}`}
        aria-current={saved.id === conversationId ? 'page' : undefined}
      >
        {saved.title || 'Untitled conversation'}{saved.status === 'archived' ? ' · Archived' : ''}
      </a>
    {/each}
  </nav>
  {#if !$history.isPending && !$history.data?.pages.some((page) => page.items.length)}<p>
      No saved direct-chat history.
    </p>{/if}
  {#if $history.hasNextPage}<Button variant="outline" onclick={() => $history.fetchNextPage()}
      >Load more conversations</Button
    >{/if}
  {#if conversationId}
    {#if $conversation.isPending}<LoadingState>Opening conversation…</LoadingState>
    {:else if $conversation.isError || $conversation.data?.origin !== 'legacy_direct'}<FeedbackToast
        message="Saved conversation unavailable."
        variant="error"
      />
    {:else}
      <h3>{$conversation.data.title || 'Untitled conversation'}</h3>
      <p role="status">Read-only history · {$conversation.data.status}</p>
      <Button
        variant="outline"
        onclick={() => {
          title = $conversation.data?.title || '';
          editing = true;
        }}>Rename</Button
      >
      <Button
        variant="outline"
        onclick={() => update({ archived: $conversation.data?.status !== 'archived' })}
        >{$conversation.data.status === 'archived' ? 'Restore history' : 'Archive history'}</Button
      >
      {#if editing}<form
          onsubmit={(event) => {
            event.preventDefault();
            void update({ title: title.trim() || null });
          }}
        >
          <Field.Label>Conversation title<Input bind:value={title} maxlength={300} /></Field.Label>
          <Button type="submit">Save title</Button>
          <Button variant="outline" onclick={() => (editing = false)}>Cancel</Button>
        </form>{/if}
      <FeedbackToast message={$items.error ? explain($items.error) : ''} variant="error" />
      {#each $items.data?.pages.flatMap((page) => page.items) ?? [] as item (item.id)}
        <ConversationTranscriptItem {item} ownerId={$conversation.data.owner_id} />
      {/each}
      {#if $items.hasNextPage}<Button variant="outline" onclick={() => $items.fetchNextPage()}
          >Load more items</Button
        >{/if}
      <details>
        <summary>Historical requests and usage</summary>
        <FeedbackToast message={$runs.error ? explain($runs.error) : ''} variant="error" />
        {#each $runs.data?.pages.flatMap((page) => page.items) ?? [] as run (run.id)}
          <article>
            <p>
              {run.requested_model || 'Unknown model'} · {run.status.toLowerCase()} · {new Date(
                run.created_at,
              ).toLocaleString()}
            </p>
            {#if run.failure_code}<p>{run.failure_code.replaceAll('_', ' ')}</p>{/if}
            {#each run.usage?.observations ?? [] as observation, index (index)}
              <p>
                Observed tokens: input {observation.input_tokens ?? 'unknown'}, output {observation.output_tokens ??
                  'unknown'} ({observation.source.toLowerCase().replaceAll('_', ' ')})
              </p>
            {/each}
            {#each run.usage?.reservations ?? [] as reservation, index (index)}
              <p>
                Reserved budget: {reservation.tokens} tokens · {reservation.cost_microusd} micro-USD
              </p>
            {/each}
          </article>
        {/each}
        {#if $runs.hasNextPage}<Button variant="outline" onclick={() => $runs.fetchNextPage()}
            >Load more requests</Button
          >{/if}
      </details>
    {/if}
  {/if}
</section>

<style>
  nav {
    display: grid;
    gap: 8px;
    margin: 16px 0;
  }
  a[aria-current='page'] {
    font-weight: 600;
  }
  details {
    margin-top: 24px;
  }
  details article {
    padding: 12px 0;
    border-bottom: 1px solid var(--border);
  }
</style>
