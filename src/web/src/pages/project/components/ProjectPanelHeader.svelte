<script lang="ts">
  import type { Snippet } from 'svelte';
  let {
    title,
    actions,
    onTitleClick,
  }: { title: string; actions?: Snippet; onTitleClick?: () => void } = $props();
</script>

<header class="project-panel-header">
  <h2>
    {#if onTitleClick}<button
        type="button"
        aria-label={`Project information: ${title}`}
        aria-haspopup="dialog"
        onclick={onTitleClick}>{title}</button
      >{:else}{title}{/if}
  </h2>
  {#if actions}<div class="header-actions">{@render actions()}</div>{/if}
</header>

<style>
  .project-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    height: var(--project-nav-height, 32px);
    min-height: var(--project-nav-height, 32px);
    box-sizing: border-box;
    flex-shrink: 0;
    margin-inline: -12px;
    padding: 0 12px;
    border-bottom: 1px solid var(--border);
    background: var(--sidebar);
  }
  h2 {
    margin: 0;
    min-width: 0;
    color: var(--foreground);
    font-family: var(--font-sans);
    font-size: 12px;
    font-weight: 600;
    line-height: 16px;
  }
  h2 button {
    text-align: left;
    cursor: pointer;
  }
  h2 button:hover {
    text-decoration: underline;
  }
  h2 button:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 2px;
  }
  .header-actions :global(button) {
    height: 20px;
    width: 20px;
    padding: 0;
    align-items: center;
    justify-content: center;
  }
  .header-actions :global(svg) {
    width: 14px;
    height: 14px;
  }
  .header-actions {
    display: flex;
    align-items: center;
    gap: 4px;
    flex-shrink: 0;
  }
</style>
