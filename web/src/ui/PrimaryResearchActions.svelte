<script lang="ts">
  import { Button } from '../lib/components/ui/button';
  export type PrimaryResearchAction = 'PROBLEM_OR_CLAIM' | 'ATTEMPT' | 'PROOF';

  let {
    compact = false,
    available,
    onSelect,
  }: {
    compact?: boolean;
    available: boolean;
    onSelect: (action: PrimaryResearchAction) => void;
  } = $props();

  const actions: Array<{ id: PrimaryResearchAction; title: string; detail: string }> = [
    {
      id: 'PROBLEM_OR_CLAIM',
      title: 'State a problem or claim',
      detail: 'Describe the question or assertion that the workspace will investigate.',
    },
    {
      id: 'ATTEMPT',
      title: 'Record an attempt',
      detail: 'Pin an exact target and retain what worked, failed, and was learned.',
    },
    {
      id: 'PROOF',
      title: 'Write a proof sketch',
      detail: 'Choose an exact conclusion and an ordered set of required premises.',
    },
  ];
</script>

<section class:compact aria-labelledby="primary-research-actions">
  <h3 id="primary-research-actions">Create research</h3>
  {#if !compact}<p class="muted">Choose a starting point for your contribution.</p>{/if}
  <div class="primary-actions">
    {#each actions as action (action.id)}
      <Button
        variant="outline"
        class="h-auto whitespace-normal"
        type="button"
        disabled={!available}
        onclick={() => onSelect(action.id)}
      >
        <span class="action-title">{action.title}</span>{#if !compact}<span>{action.detail}</span
          >{/if}
      </Button>
    {/each}
  </div>
</section>

<style>
  section {
    display: grid;
    gap: 1rem;
    margin-bottom: 24px;
  }
  .primary-actions {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr));
    gap: 0.75rem;
  }
  .primary-actions :global(button) {
    display: grid;
    gap: 0.4rem;
    align-content: start;
    min-height: 8rem;
    text-align: left;
    padding: 16px;
  }
  .primary-actions :global(button span) {
    font-weight: 400;
  }
  .action-title {
    font-weight: 400;
  }
  .compact {
    gap: 8px;
    margin-bottom: 20px;
  }
  .compact h3 {
    font-size: 13px;
    font-weight: 400;
    color: var(--muted-foreground);
  }
  .compact .primary-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .compact .primary-actions :global(button) {
    min-height: 36px;
    padding: 8px 10px;
    font-size: 13px;
  }
  h3,
  p {
    margin: 0;
  }
  @media (max-width: 760px) {
    .primary-actions {
      grid-template-columns: 1fr;
    }
    .primary-actions :global(button) {
      min-height: auto;
    }
  }
</style>
