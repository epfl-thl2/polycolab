<script lang="ts">
  import { UserRound, Sparkles } from '@lucide/svelte';
  import { reviewCount } from '../lib/review-display';
  import type { ReviewSummary } from '../lib/reviews-api';
  let { review }: { review: ReviewSummary } = $props();
</script>

<span class="review-signals">
  {#each [['human', 'Human'], ['ai', 'AI']] as [key, label] (key)}
    {@const counts = key === 'human' ? review.human : review.ai}
    {#if reviewCount(counts)}
      <span
        class="review-actor"
        title={`${label} reviewed: ${reviewCount(counts)}`}
        aria-label={`${label} reviewed`}
      >
        {#if key === 'human'}<UserRound size={13} />{:else}<Sparkles size={13} />{/if}
      </span>
    {/if}
  {/each}
</span>

<style>
  .review-signals {
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }
  .review-actor {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 3px 4px;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--panel);
    color: var(--foreground);
  }
</style>
