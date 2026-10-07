<script lang="ts">
  import { Badge } from '../lib/components/ui/badge';
  import type { CatalogueEntry } from '../lib/catalogue-api';
  import Markdown from './Markdown.svelte';
  let {
    entry,
    detailed = false,
    compact = false,
  }: { entry: CatalogueEntry; detailed?: boolean; compact?: boolean } = $props();
  const statuses = ['Established', 'Conjectured', 'Open', 'Disproved', 'Definition'];
</script>

<div class="row library-badges" class:compact>
  <Badge variant="secondary"
    >{statuses.includes(entry.reported_status)
      ? entry.reported_status
      : `Legacy status: ${entry.reported_status}`}</Badge
  >
  {#if entry.source}<Badge variant="secondary">Literature-backed</Badge>{/if}
  {#if entry.review_rationale}<Badge variant="secondary">Human-reviewed</Badge>{/if}
</div>
{#if entry.source && !compact}<p class="muted">
    {entry.source.identifier} · {entry.source.version} · {entry.source.locator}
  </p>{/if}
{#if entry.review_rationale && !compact}
  <p class="muted">
    Reviewed by {entry.reviewer_display_name || 'Researcher'}{#if entry.reviewed_at}
      · {new Date(entry.reviewed_at).toLocaleDateString()}{/if}
  </p>
  {#if detailed}<Markdown content={entry.review_rationale} />{/if}
{/if}

<style>
  .compact {
    margin-top: 4px;
  }
  .library-badges {
    gap: 0.4rem;
    margin-top: 0.5rem;
  }
  p {
    margin: 0.5rem 0;
    font-size: 0.9rem;
  }
</style>
