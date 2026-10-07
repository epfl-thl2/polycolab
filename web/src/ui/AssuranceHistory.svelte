<script lang="ts">
  import { Button } from '../lib/components/ui/button';
  import type { CorrespondenceHistoryView, EndorsementHistoryView } from '../lib/assurance-view';

  let {
    revisionId,
    endorsements,
    correspondence,
    hasMoreHistory = false,
    loadingMoreHistory = false,
    onLoadMoreHistory,
  }: {
    revisionId: string;
    endorsements: EndorsementHistoryView[];
    correspondence: CorrespondenceHistoryView[];
    hasMoreHistory?: boolean;
    loadingMoreHistory?: boolean;
    onLoadMoreHistory?: () => void;
  } = $props();
  const timeline = $derived(
    [
      ...endorsements.map((item) => ({ kind: 'endorsement' as const, item })),
      ...correspondence.map((item) => ({ kind: 'correspondence' as const, item })),
    ].sort(
      (left, right) =>
        left.item.createdAt.localeCompare(right.item.createdAt) ||
        left.kind.localeCompare(right.kind) ||
        left.item.id.localeCompare(right.item.id),
    ),
  );
</script>

<section aria-labelledby={`assurance-history-${revisionId}`}>
  <h4 id={`assurance-history-${revisionId}`}>Assurance history for this exact version</h4>
  <p class="muted">
    These assessments stay with version {revisionId}; later versions do not inherit them.
  </p>

  <h5>Chronological assessment history</h5>
  <ol>
    {#each timeline as event (`${event.kind}:${event.item.id}`)}
      {#if event.kind === 'endorsement'}
        <li>
          <strong>{event.item.active ? 'Endorsed' : 'Withdrawn'}</strong> by {event.item.author}
          <span class="muted"> · {event.item.createdAt}</span>
          <p>{event.item.rationale}</p>
        </li>
      {:else}
        <li>
          <strong>{event.item.status}</strong> for
          <a href={event.item.statementHref}>{event.item.statementTitle}</a>
          <span class="muted"> · version {event.item.statementRevisionId}</span>
          <span> · assessed by {event.item.author}</span>
          <span class="muted"> · {event.item.createdAt}</span>
          <p>{event.item.rationale}</p>
        </li>
      {/if}
    {:else}
      <li>No assessment history recorded for this version.</li>
    {/each}
  </ol>

  {#if hasMoreHistory && onLoadMoreHistory}
    <Button
      type="submit"
      variant="outline"
      class=""
      disabled={loadingMoreHistory}
      onclick={onLoadMoreHistory}
    >
      {loadingMoreHistory ? 'Loading assurance history…' : 'Load more assurance history'}
    </Button>
  {/if}
</section>

<style>
  h5 {
    margin-bottom: 0.35rem;
  }

  ol {
    margin-top: 0;
  }

  li + li {
    margin-top: 0.75rem;
  }

  li p {
    margin: 0.2rem 0 0;
  }
</style>
