<script lang="ts">
  import { UserRound, Sparkles, Check, History, ChevronDown } from '@lucide/svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import { toStore } from 'svelte/store';
  import { Button } from '../lib/components/ui/button';
  import { Textarea } from '../lib/components/ui/textarea';
  import * as DropdownMenu from '../lib/components/ui/dropdown-menu';
  import { listReviews, saveReview, type ReviewWrite } from '../lib/reviews-api';
  import { workspace, explain } from '../svelte-lib/context';
  import Markdown from './Markdown.svelte';
  let {
    versionId,
    workspaceId,
    canReview = false,
  }: { versionId: string; workspaceId?: string; canReview?: boolean } = $props();
  const { query, auth } = workspace();
  let history = $state(false);
  let cursor = $state<string>();
  let previous = $state<Awaited<ReturnType<typeof listReviews>>['items']>([]);
  const reviews = createQuery(
    toStore(() => ({
      queryKey: ['object-reviews', versionId, workspaceId, history, cursor],
      queryFn: () => listReviews(versionId, workspaceId, cursor, !history),
    })),
  );
  let rationale = $state('');
  let savedState = $state<{ version: string; active: boolean; comment: string }>();
  let editing = $state(false);
  const own = $derived(
    [...previous, ...($reviews.data?.items ?? [])].filter((item) => item.is_mine).at(-1),
  );
  const reviewed = $derived(
    savedState?.version === versionId ? savedState.active : Boolean(own && !own.withdrawn),
  );
  const savedComment = $derived(
    savedState?.version === versionId ? savedState.comment : (own?.rationale ?? ''),
  );
  let busy = $state(false);
  let error = $state('');
  let notice = $state('');
  let receipt: { body: string; key: string } | undefined;
  $effect(() => {
    void versionId;
    void history;
    cursor = undefined;
    previous = [];
    rationale = '';
    editing = false;
    error = '';
    notice = '';
  });
  async function submit(event?: SubmitEvent, remove = false) {
    event?.preventDefault();
    if (busy) return;
    busy = true;
    error = '';
    notice = '';
    const body: ReviewWrite = {
      object_version_id: versionId,
      outcome: remove ? null : 'REVIEWED',
      scope: 'Whole version',
      rationale,
      withdrawn: remove,
      evidence_object_version_ids: [],
    };
    const serialized = JSON.stringify(body);
    if (receipt?.body !== serialized) receipt = { body: serialized, key: crypto.randomUUID() };
    try {
      await saveReview(body, receipt.key);
      receipt = undefined;
      savedState = { version: versionId, active: !remove, comment: rationale };
      editing = false;
      notice = remove ? 'Review removed.' : 'Review saved.';
      rationale = '';
      cursor = undefined;
      previous = [];
      await query.invalidateQueries({ queryKey: ['object-reviews'] });
      await query.invalidateQueries({ queryKey: ['review-summaries'] });
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
</script>

<section aria-label="Version reviews" class="reviews">
  {#if canReview}
    <form onsubmit={submit} class="review-editor">
      <div class="editor-heading">
        <div class="identity"><strong>{auth.label}</strong><span>Human</span></div>
        {#if reviewed && !editing}
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              {#snippet child({ props })}<Button
                  {...props}
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  aria-label="Reviewed — review actions"
                  ><Check size={14} />Reviewed<ChevronDown size={12} /></Button
                >{/snippet}
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="end">
              <DropdownMenu.Item
                onSelect={() => {
                  rationale = savedComment;
                  editing = true;
                }}>Edit comment</DropdownMenu.Item
              >
              <DropdownMenu.Item
                onSelect={() => {
                  void submit(undefined, true);
                }}>Remove review</DropdownMenu.Item
              >
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        {:else}<Button type="submit" variant="outline" size="sm" disabled={busy}
            >{busy ? 'Saving…' : editing ? 'Save comment' : 'Mark as reviewed'}</Button
          >{/if}
      </div>
      {#if !reviewed || editing}
        <Textarea
          aria-label="Comment (optional)"
          maxlength={20000}
          rows={2}
          bind:value={rationale}
          disabled={busy}
          placeholder="Add a comment…"
          class="review-comment"
        />
        {#if editing}<Button
            variant="ghost"
            size="sm"
            onclick={() => {
              editing = false;
              rationale = '';
            }}>Cancel</Button
          >{/if}
      {:else if savedComment}<div class="own-comment"><Markdown content={savedComment} /></div>{/if}
      {#if error}<p role="alert" class="error">{error} Your draft is retained.</p>{/if}
      {#if notice}<span role="status" class="notice">{notice}</span>{/if}
    </form>
  {/if}
  <div class="list-heading">
    <h3>{history ? 'Review history' : 'Reviews'}</h3>
    <Button variant="ghost" size="sm" onclick={() => (history = !history)} aria-pressed={history}>
      <History size={14} aria-hidden="true" />{history ? 'Current' : 'History'}
    </Button>
  </div>
  {#if $reviews.isPending}<p class="empty" role="status">Loading reviews…</p>
  {:else if $reviews.isError}<p role="alert">{explain($reviews.error)}</p>
    <Button variant="outline" onclick={() => $reviews.refetch()}>Retry reviews</Button>
  {:else}
    <div class="review-list">
      {#each [...previous, ...($reviews.data?.items ?? [])] as review (review.id)}
        <article class="review" class:withdrawn={review.withdrawn}>
          <div class="review-heading">
            <span class="avatar" aria-hidden="true"
              >{#if review.actor_kind === 'HUMAN'}<UserRound size={16} />{:else}<Sparkles
                  size={16}
                />{/if}</span
            >
            <div class="identity">
              <strong>{review.reviewer_name}</strong>
              <span
                >{review.actor_kind === 'HUMAN' ? 'Human' : 'AI'}{review.model_id
                  ? ` · ${review.model_id}`
                  : ''}{review.self_review ? ' · Self-review' : ''}</span
              >
            </div>
            <span class="review-badge"
              >{#if !review.withdrawn}<Check size={12} aria-hidden="true" />{/if}{review.withdrawn
                ? 'Removed'
                : 'Reviewed'}</span
            >
          </div>
          {#if review.rationale.trim()}<div class="review-body">
              <Markdown content={review.rationale} />
            </div>{/if}
          <time datetime={review.created_at} title={new Date(review.created_at).toLocaleString()}
            >{new Date(review.created_at).toLocaleDateString(undefined, {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
            })}</time
          >
        </article>
      {:else}<p class="empty">No reviews yet for this version.</p>{/each}
    </div>
    {#if $reviews.data?.next_cursor}<Button
        variant="outline"
        size="sm"
        onclick={() => {
          previous = [...previous, ...($reviews.data?.items ?? [])];
          cursor = $reviews.data?.next_cursor ?? undefined;
        }}>Load more reviews</Button
      >{/if}
  {/if}
</section>

<style>
  .reviews {
    display: grid;
    gap: 12px;
    font-size: 13px;
  }
  .review-editor {
    display: grid;
    gap: 12px;
    padding: 0 0 12px;
    border-bottom: 1px solid var(--border);
  }
  .editor-heading,
  .review-heading {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .editor-heading .identity {
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .editor-heading .identity span::before {
    content: '· ';
  }
  .avatar {
    display: grid;
    place-items: center;
    flex-shrink: 0;
    width: 30px;
    height: 30px;
    border: 1px solid var(--sidebar-border);
    border-radius: 50%;
    color: var(--muted-foreground);
    background: var(--sidebar);
  }
  .identity {
    display: grid;
    gap: 1px;
    min-width: 0;
    flex: 1;
  }
  strong {
    font-size: 13px;
    font-weight: 500;
    overflow-wrap: anywhere;
  }
  .identity span,
  time {
    font-size: 11px;
    color: var(--muted-foreground);
  }
  .review-editor :global(textarea) {
    min-height: 52px;
    font-size: 13px;
  }
  .notice {
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .own-comment {
    font-size: 13px;
  }
  .own-comment :global(p) {
    margin: 0;
  }
  .list-heading {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  h3 {
    font-size: 12px;
    font-weight: 500;
    margin: 0;
    color: var(--muted-foreground);
  }
  .review-list {
    display: grid;
  }
  .review {
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }
  .review:first-child {
    padding-top: 0;
  }
  .review:last-child {
    border-bottom: 0;
  }
  .review.withdrawn {
    opacity: 0.65;
  }
  .review-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    padding: 3px 6px;
    border-radius: 4px;
    background: var(--sidebar);
    white-space: nowrap;
  }
  .review-body {
    margin: 8px 0 6px 38px;
    font-size: 13px;
    overflow-wrap: anywhere;
  }
  .review-body :global(.prose) {
    font-size: 13px;
    line-height: 1.5;
  }
  .review-body :global(p) {
    margin: 4px 0;
  }
  time {
    display: block;
    margin: 5px 0 0 38px;
  }
  .empty {
    padding: 16px 12px;
    margin: 0;
    border: 1px dashed var(--border);
    border-radius: 6px;
    text-align: center;
    color: var(--muted-foreground);
  }
  .error {
    margin: 0;
    color: var(--destructive);
  }
</style>
