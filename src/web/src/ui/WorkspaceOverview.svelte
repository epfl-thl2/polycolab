<script lang="ts">
  import Markdown from './Markdown.svelte';
  let { description }: { description?: string | null } = $props();
</script>

<section class="overview-description" aria-labelledby="workspace-description-heading">
  <div class="description-heading">
    <h2 id="workspace-description-heading">Description</h2>
  </div>
  {#if description?.trim()}<Markdown content={description} />{:else}<p class="muted">
      No project description yet.
    </p>{/if}
</section>

<style>
  .overview-description {
    max-width: 70ch;
    margin: 0 0 28px;
    overflow-wrap: anywhere;
  }
  .description-heading {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 8px 16px;
    margin-bottom: 8px;
  }
  h2 {
    color: var(--muted-foreground);
    font-size: 13px;
    font-weight: 400;
    margin: 0;
  }
  .overview-description :global(.prose) {
    font-family: var(--font-sans);
    font-size: 14px;
    font-weight: 400;
    line-height: 1.65;
    color: var(--foreground);
  }
  .overview-description > p {
    font-size: 14px;
    line-height: 1.65;
    margin: 0;
  }
  .overview-description :global(.prose p) {
    margin: 10px 0;
  }
  .overview-description :global(.prose :is(h1, h2, h3, h4, h5, h6)) {
    font-family: inherit;
    font-size: 16px;
    font-weight: 500;
    line-height: 1.4;
    margin: 16px 0 8px;
  }
  .overview-description :global(.prose > :first-child) {
    margin-top: 0;
  }
  .overview-description :global(.prose > :last-child) {
    margin-bottom: 0;
  }
</style>
