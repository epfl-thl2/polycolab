<script lang="ts">
  import { Button } from '../lib/components/ui/button';
  import {
    canTargetWithResearchAttempt,
    type ExactResearchRevisionView,
    type ResearchAttemptView,
  } from '../lib/research-structure-view';

  let {
    target,
    attempts,
    canCreate = false,
    hasMore = false,
    loadingMore = false,
    onCreate,
    onLoadMore,
  }: {
    target: ExactResearchRevisionView;
    attempts: ResearchAttemptView[];
    canCreate?: boolean;
    hasMore?: boolean;
    loadingMore?: boolean;
    onCreate?: () => void;
    onLoadMore?: () => void;
  } = $props();

  const progressLabel = (progress: ResearchAttemptView['reportedProgress']) =>
    progress.charAt(0) + progress.slice(1).toLowerCase();
</script>

<section aria-labelledby={`attempts-${target.revisionId}`}>
  <header>
    <div>
      <h2 id={`attempts-${target.revisionId}`}>Research attempts</h2>
      <p class="muted">
        Attributable activity targeting <a href={target.href}>{target.title}</a>, exact version
        {target.revisionId}. Attempts do not edit the target or establish assurance.
      </p>
    </div>
    {#if canCreate && canTargetWithResearchAttempt(target)}
      <Button type="button" onclick={onCreate}>Record research attempt</Button>
    {/if}
  </header>

  {#if !canTargetWithResearchAttempt(target)}
    <p class="state-label">Research attempts cannot target other research attempts.</p>
  {/if}

  {#each attempts as attempt (attempt.attemptRevisionId)}
    <article class="panel" aria-labelledby={`attempt-${attempt.attemptRevisionId}`}>
      <header>
        <div>
          <h3 id={`attempt-${attempt.attemptRevisionId}`}>{attempt.outcome}</h3>
          <p class="muted">
            {attempt.actorKind === 'AGENT' ? 'Agent' : 'Human'} research attempt
          </p>
          <p class="muted">
            {attempt.author} · {attempt.createdAt} · version {attempt.attemptRevisionId}
          </p>
        </div>
        <strong class="state-label">Reported {progressLabel(attempt.reportedProgress)}</strong>
      </header>

      <p>{attempt.findings}</p>
      <p class="muted">
        Exact target: <a href={attempt.target.href}>{attempt.target.title}</a> · version
        {attempt.target.revisionId}
      </p>

      <section aria-labelledby={`evidence-${attempt.attemptRevisionId}`}>
        <h4 id={`evidence-${attempt.attemptRevisionId}`}>Exact evidence</h4>
        {#if attempt.evidence.length > 0}
          <ul>
            {#each attempt.evidence as item (item.id)}
              <li>
                <strong>{item.role}:</strong>
                <a href={item.revision.href}>{item.revision.title}</a>
                <span class="muted"> · version {item.revision.revisionId}</span>
              </li>
            {/each}
          </ul>
        {:else}
          <p>No evidence linked.</p>
        {/if}
      </section>

      {#if attempt.resultingRevision}
        <p>
          <strong>Resulting target version:</strong>
          <a href={attempt.resultingRevision.href}>{attempt.resultingRevision.title}</a>
          <span class="muted"> · version {attempt.resultingRevision.revisionId}</span>
        </p>
      {/if}

      <p class="muted">
        This research attempt is distinct from controller execution attempts and retries.
      </p>
    </article>
  {:else}
    <p>No research attempts are visible for this exact target version.</p>
  {/each}

  {#if hasMore}
    <Button variant="outline" type="button" class="" disabled={loadingMore} onclick={onLoadMore}>
      {loadingMore ? 'Loading attempt history…' : 'Load more attempts'}
    </Button>
  {/if}
</section>

<style>
  section,
  article {
    display: grid;
    gap: 0.75rem;
  }

  section > header,
  article > header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 1rem;
  }

  h2,
  h3,
  h4,
  p,
  ul {
    margin-top: 0;
  }

  .state-label {
    display: inline-block;
    padding: 0.2rem 0.45rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
    font-size: 0.85rem;
  }

  @media (max-width: 520px) {
    section > header,
    article > header {
      display: grid;
    }
  }
</style>
