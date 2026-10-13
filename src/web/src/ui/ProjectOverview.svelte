<script lang="ts">
  import Markdown from './Markdown.svelte';
  let {
    name,
    description,
    visibility,
    role,
  }: {
    name: string;
    description?: string | null;
    visibility: string;
    role?: string | null;
  } = $props();
  const access = $derived(
    role === 'OWNER'
      ? 'Owner'
      : role === 'CONTRIBUTOR'
        ? 'Contributor'
        : role === 'READ_ONLY'
          ? 'Read only'
          : 'Visitor',
  );
</script>

<section class="overview-description" aria-label="Project overview">
  <h1>{name}</h1>
  {#if description?.trim()}<Markdown content={description} />{:else}<p class="muted">
      No project description yet.
    </p>{/if}
  <p class="overview-meta" aria-label="Project visibility and access">
    <span>{visibility === 'PUBLIC' ? 'Public' : 'Private'}</span><span aria-hidden="true">·</span
    ><span>{access}</span>
  </p>
</section>

<style>
  .overview-description {
    max-width: 70ch;
    margin: 0 0 28px;
    overflow-wrap: anywhere;
  }
  h1 {
    font-size: clamp(22px, 2.2vw, 30px);
    font-weight: 400;
    line-height: 1.25;
    margin: 0 0 16px;
  }
  .overview-description > .overview-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-top: 16px;
    color: var(--muted-foreground);
    font-size: 12px;
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
