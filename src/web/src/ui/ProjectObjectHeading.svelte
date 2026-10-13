<script lang="ts">
  import type { Snippet } from 'svelte';
  import ObjectKindBadge from './ObjectKindBadge.svelte';
  let {
    title,
    kind,
    number,
    actions,
  }: { title: string; kind: string; number?: number; actions?: Snippet } = $props();
</script>

<div class="project-object-heading">
  <div class="title-row">
    <h3>{title}</h3>
    {#if actions}<div class="actions">{@render actions()}</div>{/if}
  </div>
  <div class="metadata">
    <ObjectKindBadge {kind} />{#if number !== undefined}<span>v{number}</span>{/if}
  </div>
</div>

<style>
  .project-object-heading {
    padding: 8px 10px;
    border: 1px solid var(--brand);
    border-radius: var(--radius-lg);
    background: var(--panel);
    color: var(--foreground);
    box-shadow: 0 1px 3px var(--polycolab-shadow);
    margin-bottom: 10px;
  }
  .title-row {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 8px;
  }
  h3 {
    font-size: 17px;
    font-weight: 400;
    line-height: 1.4;
    overflow-wrap: anywhere;
    margin: 0 0 6px;
  }
  .actions {
    display: flex;
    flex-shrink: 0;
    gap: 2px;
  }
  .metadata {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--muted-foreground);
    font-size: 12px;
  }
</style>
