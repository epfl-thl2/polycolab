<script lang="ts">
  import { reviewCount, reviewLabel } from '../lib/review-display';
  import type { ReviewSummary } from '../lib/reviews-api';
  import ReviewSignals from './ReviewSignals.svelte';
  import ObjectKindBadge from './ObjectKindBadge.svelte';
  import * as Field from '../lib/components/ui/field';
  import { Input } from '../lib/components/ui/input';
  import { Button } from '../lib/components/ui/button';
  import { searchMapObjects, type WorkspaceMap } from '../lib/workspace-map';
  let {
    data,
    objectId = $bindable(''),
    summaries = [],
    onreview = () => {},
  }: {
    data: WorkspaceMap;
    objectId?: string;
    summaries?: ReviewSummary[];
    onreview?: (id: string) => void;
  } = $props();
  let searchInput = $state<HTMLInputElement | null>(null);
  export function focusSearch() {
    searchInput?.scrollIntoView({
      block: 'center',
      behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
    });
    searchInput?.focus({ preventScroll: true });
  }
  let query = $state('');
  let visibleCount = $state(100);
  const matches = $derived(query.trim() ? searchMapObjects(data.objects, query) : data.objects);
  function focus(id: string) {
    objectId = id;
  }
</script>

<section class="object-browser" aria-label="Find and focus objects">
  <Field.Label
    >Focus on an object<Input
      bind:ref={searchInput}
      type="search"
      bind:value={query}
      placeholder="Search objects…"
      title="Search titles, content, types, or IDs. Combine words, use &quot;exact phrases&quot;, or -exclude a word."
      oninput={() => (visibleCount = 100)}
    /></Field.Label
  >
  <h2>
    {query.trim() ? 'Search results' : 'All objects'} <span class="muted">({matches.length})</span>
  </h2>
  {#if query.trim()}<div class="search-status">
      <p class="muted" role="status">{matches.length} matching objects</p>
      <Button variant="ghost" onclick={() => (query = '')}>Clear search</Button>
    </div>{/if}
  <ul
    class="object-list"
    aria-label={query.trim() ? 'Focused object search results' : 'All objects'}
  >
    {#each matches.slice(0, visibleCount) as object (object.id)}
      {@const review = summaries.find(
        (item) => item.object_version_id === object.current_object_version.id,
      )}
      <li style="display: flex; align-items: center; gap: 4px;">
        <button
          style="flex: 1; min-width: 0;"
          type="button"
          class="object-card"
          class:selected={object.id === objectId}
          aria-pressed={object.id === objectId}
          aria-label={object.current_object_version.content.title}
          onclick={() => focus(object.id)}
        >
          <span class="card-title" title={object.current_object_version.content.title}
            >{object.current_object_version.content.title}</span
          >
          <ObjectKindBadge kind={object.kind} />
        </button>
        {#if review && reviewCount(review.human) + reviewCount(review.ai)}
          <Button
            variant="ghost"
            size="sm"
            aria-label={`Reviews for ${object.current_object_version.content.title}`}
            onclick={() => onreview(object.id)}
            title={reviewLabel(review)}
          >
            <ReviewSignals {review} />
          </Button>
        {/if}
      </li>
    {:else}<li class="muted">No matching objects. Try fewer terms.</li>{/each}
  </ul>
  {#if visibleCount < matches.length}<Button variant="outline" onclick={() => (visibleCount += 100)}
      >Show more objects</Button
    >{/if}
</section>

<style>
  .search-status {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
  }
  .object-browser {
    --muted: var(--polycolab-groseille-soft);
    margin-top: 24px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--sidebar);
  }
  .object-browser :global(label) {
    font-weight: 400;
  }
  .object-browser :global(input) {
    background: var(--panel);
  }
  h2 {
    margin: 12px 0;
    font-size: 14px;
    font-weight: 400;
  }
  .object-list {
    display: grid;
    gap: 3px;
    padding: 0;
    margin: 0 0 12px;
    list-style: none;
  }
  .object-card {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    width: 100%;
    gap: 8px;
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
    color: var(--foreground);
    text-align: left;
    cursor: pointer;
  }
  .object-card:hover {
    border-color: var(--line-strong);
    background: var(--polycolab-groseille-soft);
  }
  .object-card:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 3px;
  }
  .object-card.selected {
    border-color: var(--brand);
    background: var(--brand-soft);
  }
  .card-title {
    font-size: 13px;
    line-height: 1.4;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
</style>
