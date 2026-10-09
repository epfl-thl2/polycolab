<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import * as Field from '../lib/components/ui/field';
  import { Button } from '../lib/components/ui/button';
  import { Textarea } from '../lib/components/ui/textarea';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery } from '@tanstack/svelte-query';
  import { workspace, explain } from '../svelte-lib/context';
  import Markdown from './Markdown.svelte';
  let {
    objectId,
    revisionId,
    canWrite,
  }: { objectId: string; revisionId: string; canWrite: boolean } = $props();
  const { api, query } = workspace();
  let text = $state('');
  let busy = $state(false);
  let error = $state('');
  const comments = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['comments', objectId],
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        api.listComments(objectId, pageParam),
      getNextPageParam: (page: { nextCursor?: string }) => page.nextCursor,
    })),
  );
  async function send(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    try {
      await api.createComment(objectId, { object_version_id: revisionId, body_md: text });
      text = '';
      await query.invalidateQueries({ queryKey: ['comments', objectId] });
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
</script>

<h2>Discussion</h2>
{#if $comments.isPending}<LoadingState>Loading discussion…</LoadingState
  >{:else if $comments.isError}<Alert.Root variant="destructive" role="alert">
    {explain($comments.error)}
  </Alert.Root>
  <Button type="submit" onclick={() => $comments.refetch()}>Retry</Button>{:else}<ul class="list">
    {#each $comments.data?.pages.flatMap((p) => p.items) ?? [] as comment (comment.id)}<li>
        <Markdown content={comment.body_md} /><small
          >{comment.author.display_name || 'Member'} · Version
          <code>{comment.object_version_id}</code></small
        >
      </li>{/each}
  </ul>
  {#if !$comments.data?.pages[0].items.length}<p class="muted">
      No discussion yet.
    </p>{/if}{/if}{#if $comments.hasNextPage}<Button
    type="submit"
    onclick={() => $comments.fetchNextPage()}>Load more comments</Button
  >{/if}{#if canWrite}<form class="mt-6" onsubmit={send}>
    <Field.Label>Add a Markdown comment<Textarea required bind:value={text}></Textarea></Field.Label
    ><small>Attached to version {revisionId}</small>{#if error}<Alert.Root
        variant="destructive"
        role="alert">{error}</Alert.Root
      >{/if}<Button type="submit" disabled={busy || !text.trim()}
      >{busy ? 'Posting…' : 'Add comment'}</Button
    >
  </form>{/if}
