<script lang="ts">
  import { Button } from '../lib/components/ui/button';
  import {
    canAnnotateResearchRevision,
    type ResearchActivityTargetKind,
    type ResearchCommentView,
    type ResearchProgressView,
  } from '../lib/research-structure-view';

  let {
    targetRevisionId,
    targetKind,
    comments,
    progress,
    canContribute = false,
    hasMore = false,
    onComment,
    onProgress,
    onLoadMore,
  }: {
    targetRevisionId: string;
    targetKind: ResearchActivityTargetKind;
    comments: ResearchCommentView[];
    progress: ResearchProgressView[];
    canContribute?: boolean;
    hasMore?: boolean;
    onComment?: () => void;
    onProgress?: () => void;
    onLoadMore?: () => void;
  } = $props();

  const annotatable = $derived(canAnnotateResearchRevision(targetKind));
</script>

<section aria-labelledby={`activity-${targetRevisionId}`}>
  <header>
    <div>
      <h2 id={`activity-${targetRevisionId}`}>Comments and progress</h2>
      <p class="muted">Pinned to exact research version {targetRevisionId}.</p>
    </div>
    {#if canContribute && annotatable}
      <div class="actions">
        <Button variant="outline" type="button" class="" onclick={onComment}>Add comment</Button>
        <Button variant="outline" type="button" class="" onclick={onProgress}
          >Report progress</Button
        >
      </div>
    {/if}
  </header>

  {#if !annotatable}
    <p class="state-label">
      Notes, summaries, comments and progress updates cannot themselves be annotated.
    </p>
  {/if}

  <div class="activity-columns">
    <section aria-labelledby={`comments-${targetRevisionId}`}>
      <h3 id={`comments-${targetRevisionId}`}>Comments</h3>
      <ol>
        {#each comments as comment (comment.id)}
          <li>
            <p>{comment.content}</p>
            <p class="muted">
              {comment.actorKind === 'AGENT' ? 'Agent' : 'Human'}
              {comment.author} ·
              {comment.createdAt} · target {comment.targetRevisionId}
            </p>
          </li>
        {:else}
          <li>No comments recorded.</li>
        {/each}
      </ol>
    </section>

    <section aria-labelledby={`progress-${targetRevisionId}`}>
      <h3 id={`progress-${targetRevisionId}`}>Append-only progress</h3>
      <ol>
        {#each progress as update (update.id)}
          <li>
            <strong>{update.label}</strong>
            <p>{update.explanation}</p>
            <p class="muted">
              {update.actorKind === 'AGENT' ? 'Agent' : 'Human'}
              {update.author} ·
              {update.createdAt} · target {update.targetRevisionId}
            </p>
          </li>
        {:else}
          <li>No progress updates recorded.</li>
        {/each}
      </ol>
      <p class="muted">Reported progress is activity, not endorsement or verification.</p>
    </section>
  </div>

  {#if hasMore}
    <Button variant="outline" type="button" class="" onclick={onLoadMore}>Load more activity</Button
    >
  {/if}
</section>

<style>
  section {
    display: grid;
    gap: 0.75rem;
  }

  section > header,
  .actions {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .activity-columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
    gap: 1rem;
  }

  h2,
  h3,
  p,
  ol {
    margin-top: 0;
  }

  .state-label {
    display: inline-block;
    width: fit-content;
    padding: 0.2rem 0.45rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
  }

  @media (max-width: 520px) {
    section > header,
    .actions {
      display: grid;
    }
  }
</style>
