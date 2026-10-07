<script lang="ts">
  import type { Snippet } from 'svelte';
  let {
    kind = 'empty',
    title,
    description,
    level = 'h2',
    children,
  }: {
    kind?: 'empty' | 'error';
    title: string;
    description: string;
    level?: 'h2' | 'h3';
    children?: Snippet;
  } = $props();
</script>

<div
  class="discovery-state"
  class:error={kind === 'error'}
  role={kind === 'error' ? 'alert' : 'status'}
>
  <svelte:element this={level}>{title}</svelte:element>
  <p>{description}</p>
  {#if children}<div class="actions">{@render children()}</div>{/if}
</div>

<style>
  .discovery-state {
    display: grid;
    gap: 12px;
    padding: 24px;
    border: 1px solid var(--line);
    border-radius: 8px;
  }
  .error {
    border-color: var(--destructive);
  }
  h2,
  h3,
  p {
    margin: 0;
  }
  h2,
  h3 {
    font-size: 18px;
    line-height: 1.3;
  }
  p {
    color: var(--muted-foreground);
    line-height: 1.6;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  @media (max-width: 700px) {
    .discovery-state {
      padding: 16px;
    }
  }
</style>
