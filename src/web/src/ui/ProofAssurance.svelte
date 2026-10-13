<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import { Button } from '../lib/components/ui/button';
  import type { ProofSketchView } from '../lib/assurance-view';
  import AssuranceHistory from './AssuranceHistory.svelte';

  let {
    alternatives,
    currentStatementRevisionId,
    hasMoreCurrent = false,
    loadingMoreCurrent = false,
    onLoadMoreCurrent,
    hasMoreHistory = false,
    loadingMoreHistory = false,
    onLoadMoreHistory,
  }: {
    alternatives: ProofSketchView[];
    currentStatementRevisionId: string;
    hasMoreCurrent?: boolean;
    loadingMoreCurrent?: boolean;
    onLoadMoreCurrent?: () => void;
    hasMoreHistory?: boolean;
    loadingMoreHistory?: boolean;
    onLoadMoreHistory?: () => void;
  } = $props();
  let showGraph = $state(false);

  const endorsementLabel = (state: ProofSketchView['endorsement']) =>
    state === 'ENDORSED'
      ? 'Endorsed'
      : state === 'WITHDRAWN'
        ? 'Withdrawn'
        : state === 'DISAGREEMENT'
          ? 'Different current positions'
          : 'Not assessed';
  const correspondenceLabel = (state: ProofSketchView['correspondence']) =>
    state === 'MATCHES'
      ? 'Matches'
      : state === 'PARTIAL'
        ? 'Partial'
        : state === 'MISMATCH'
          ? 'Mismatch'
          : state === 'DISAGREEMENT'
            ? 'Different current positions'
            : 'Not assessed';
</script>

<section aria-labelledby="proof-alternatives-heading">
  <h2 id="proof-alternatives-heading">Alternative proof sketches</h2>
  <p class="muted">
    Each alternative has its own jointly required premises and version-specific assurance. These
    signals do not establish truth or catalogue admission.
  </p>

  {#if alternatives.length > 0}
    <Button
      type="submit"
      variant="outline"
      class=""
      aria-expanded={showGraph}
      onclick={() => (showGraph = !showGraph)}
      >{showGraph ? 'Hide prerequisite graph' : 'Show prerequisite graph'}</Button
    >
    {#if showGraph}
      {#await import('./ProofGraph.svelte')}<LoadingState>Loading prerequisite graph…</LoadingState>
      {:then module}<module.default {alternatives} />{/await}
    {/if}
  {/if}

  {#each alternatives as proof (proof.sketchId)}
    <article class="panel proof-alternative" aria-labelledby={`proof-title-${proof.sketchId}`}>
      <header>
        <div>
          <h3 id={`proof-title-${proof.sketchId}`}>
            <a href={proof.href}>{proof.title}</a>
          </h3>
          <p class="muted">{proof.author} · {proof.sketchRevisionId}</p>
          {#if proof.recordKind === 'PROOF'}
            <strong class="state-label">Legacy proof record</strong>
          {/if}
        </div>
        {#if proof.historical || proof.conclusion.revisionId !== currentStatementRevisionId}
          <strong class="state-label">Historical version</strong>
        {/if}
      </header>

      <dl class="assurance-grid">
        <div>
          <dt>Reported sketch progress</dt>
          <dd>{proof.reportedProgress}</dd>
        </div>
        <div>
          <dt>Human endorsement</dt>
          <dd>{endorsementLabel(proof.endorsement)}</dd>
        </div>
        <div>
          <dt>Formal/informal correspondence</dt>
          <dd>{correspondenceLabel(proof.correspondence)}</dd>
        </div>
        <div>
          <dt>Machine observations</dt>
          <dd>{proof.machineObservations.length === 0 ? 'None recorded' : 'Recorded below'}</dd>
        </div>
      </dl>

      <section class="current-positions" aria-labelledby={`current-positions-${proof.sketchId}`}>
        <h4 id={`current-positions-${proof.sketchId}`}>Current assessor positions</h4>
        <p class="muted">
          Each position belongs to one assessor and this exact version. Different positions are
          retained rather than combined into a verdict.
        </p>
        <h5>Human endorsement</h5>
        <ul>
          {#each proof.currentEndorsements as item (item.id)}
            <li>
              <strong>{item.author}</strong> · {item.active ? 'Endorsed' : 'Withdrawn'}
              <span class="muted"> · {item.createdAt}</span>
              {#if item.rationale}<p>{item.rationale}</p>{/if}
            </li>
          {:else}
            <li>No current human endorsement position.</li>
          {/each}
        </ul>
        <h5>Formal/informal correspondence</h5>
        <ul>
          {#each proof.currentCorrespondence as item (item.id)}
            <li>
              <strong>{item.author}</strong> · {item.status} for
              <a href={item.statementHref}>{item.statementTitle}</a>
              <span class="muted"> · version {item.statementRevisionId} · {item.createdAt}</span>
              {#if item.rationale}<p>{item.rationale}</p>{/if}
            </li>
          {:else}
            <li>No current correspondence position for this exact conclusion.</li>
          {/each}
        </ul>
        {#if hasMoreCurrent && onLoadMoreCurrent}
          <Button
            type="submit"
            variant="outline"
            class=""
            disabled={loadingMoreCurrent}
            onclick={onLoadMoreCurrent}
          >
            {loadingMoreCurrent ? 'Loading current positions…' : 'Load more current positions'}
          </Button>
        {/if}
      </section>

      <section aria-labelledby={`conclusion-${proof.sketchId}`}>
        <h4 id={`conclusion-${proof.sketchId}`}>Exact conclusion</h4>
        <a href={proof.conclusion.href}>{proof.conclusion.title}</a>
        <p class="muted">Version {proof.conclusion.revisionId}</p>
      </section>

      <section aria-labelledby={`premises-${proof.sketchId}`}>
        <h4 id={`premises-${proof.sketchId}`}>Jointly required premises</h4>
        {#if proof.premises.length > 0}
          <ul>
            {#each proof.premises as premise (premise.revisionId)}
              <li>
                <a href={premise.href}>{premise.title}</a>
                <span class="muted"> · version {premise.revisionId}</span>
              </li>
            {/each}
          </ul>
        {:else}
          <p>No premises recorded for this exact proof-sketch version.</p>
        {/if}
      </section>

      <section aria-labelledby={`assumptions-${proof.sketchId}`}>
        <h4 id={`assumptions-${proof.sketchId}`}>Unresolved assumptions</h4>
        {#if proof.unresolvedAssumptions.length > 0}
          <ul>
            {#each proof.unresolvedAssumptions as assumption, index (`${proof.sketchRevisionId}-${index}`)}
              <li>{assumption}</li>
            {/each}
          </ul>
          <p class="state-label">Conditional result</p>
        {:else}
          <p>None reported.</p>
        {/if}
      </section>

      {#if proof.machineObservations.length > 0}
        <section aria-labelledby={`observations-${proof.sketchId}`}>
          <h4 id={`observations-${proof.sketchId}`}>Machine observations</h4>
          <ul>
            {#each proof.machineObservations as observation (observation.id)}
              <li>
                <strong>{observation.label}:</strong>
                {observation.outcome}
                {#if observation.observedAt}<span class="muted">
                    · {observation.observedAt}</span
                  >{/if}
              </li>
            {/each}
          </ul>
          <p class="muted">A machine observation is not human endorsement or correspondence.</p>
        </section>
      {/if}

      <AssuranceHistory
        revisionId={proof.sketchRevisionId}
        endorsements={proof.endorsementHistory}
        correspondence={proof.correspondenceHistory}
        {hasMoreHistory}
        {loadingMoreHistory}
        {onLoadMoreHistory}
      />
    </article>
  {:else}
    <p>No visible proof-sketch alternatives conclude this exact statement version.</p>
  {/each}
</section>

<style>
  .proof-alternative {
    display: grid;
    gap: 1rem;
  }

  .proof-alternative > header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 1rem;
  }

  .proof-alternative h3,
  .proof-alternative h4,
  .proof-alternative p {
    margin-top: 0;
  }

  .state-label {
    display: inline-block;
    padding: 0.2rem 0.45rem;
    border: 1px solid currentColor;
    border-radius: 0.25rem;
    font-size: 0.85rem;
  }

  .assurance-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
    gap: 0.75rem;
    margin: 0;
  }

  .assurance-grid > div {
    padding: 0.75rem;
    border: 1px solid var(--demo-line, #c9cecc);
    border-radius: 0.35rem;
  }

  .assurance-grid dt {
    font-size: 0.8rem;
    font-weight: 700;
  }

  .assurance-grid dd {
    margin: 0.2rem 0 0;
  }

  .current-positions ul {
    margin-top: 0.35rem;
  }

  .current-positions li + li {
    margin-top: 0.75rem;
  }

  .current-positions li p {
    margin: 0.2rem 0 0;
  }

  @media (max-width: 520px) {
    .proof-alternative > header {
      display: grid;
    }
  }
</style>
