<script lang="ts">
  import LoadingState from './LoadingState.svelte';
  import * as Field from '../lib/components/ui/field';
  import { Badge } from '../lib/components/ui/badge';
  import { Input } from '../lib/components/ui/input';
  import { Button } from '../lib/components/ui/button';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import CatalogueAdmissionForm from './CatalogueAdmissionForm.svelte';
  import { onMount, tick } from 'svelte';
  import { projectContext, explain } from '../svelte-lib/context';
  import type { DiscoveryFilters } from '../lib/catalogue-api';
  let {
    entryId,
    revisionId,
    publicationId,
  }: { entryId?: string; revisionId?: string; publicationId?: string } = $props();
  const { catalogue, auth } = projectContext();
  let page = $state<Awaited<ReturnType<typeof catalogue.search>>>();
  let q = $state('');
  let kind = $state<DiscoveryFilters['kind']>();
  let status = $state('');
  let source = $state('');
  let author = $state('');
  let filtersOpen = $state(false);
  let searchGeneration = 0;
  let appliedFilters = $state<DiscoveryFilters>({});
  let error = $state('');
  let busy = $state(false);
  let admitting = $state(false);
  let admissionHeading = $state<HTMLHeadingElement>();
  const kinds: NonNullable<DiscoveryFilters['kind']>[] = [
    'PROBLEM',
    'DEFINITION',
    'STATEMENT',
    'PROOF',
    'ATTEMPT',
    'NOTE',
    'FORMALIZATION',
  ];
  const kindLabels: Record<NonNullable<DiscoveryFilters['kind']>, string> = {
    PROBLEM: 'Problem',
    DEFINITION: 'Definition',
    STATEMENT: 'Statement',
    PROOF: 'Proof',
    ATTEMPT: 'Research attempt',
    NOTE: 'Note',
    FORMALIZATION: 'Formalization',
  };
  function countAdvancedFilters(filters: DiscoveryFilters) {
    return (
      Number(Boolean(filters.kind)) +
      Number(Boolean(filters.source)) +
      Number(Boolean(filters.author)) +
      Number(Boolean(filters.status))
    );
  }
  const advancedFilterCount = $derived(countAdvancedFilters(appliedFilters));
  const hasAppliedSearch = $derived(Boolean(appliedFilters.q?.trim()) || advancedFilterCount > 0);

  function normalizedFilters(): DiscoveryFilters {
    return {
      q: q.trim() || undefined,
      kind,
      status: status.trim() || undefined,
      source: source.trim() || undefined,
      author: author.trim() || undefined,
    };
  }
  function readUrlFilters(): DiscoveryFilters {
    const params = new URL(location.href).searchParams;
    const requestedKind = params.get('kind');
    return {
      q: params.get('q')?.trim() || undefined,
      kind: kinds.includes(requestedKind as NonNullable<DiscoveryFilters['kind']>)
        ? (requestedKind as NonNullable<DiscoveryFilters['kind']>)
        : undefined,
      source: params.get('source')?.trim() || undefined,
      author: params.get('author')?.trim() || undefined,
      status: params.get('status')?.trim() || undefined,
    };
  }
  function setDrafts(filters: DiscoveryFilters) {
    q = filters.q ?? '';
    kind = filters.kind ?? undefined;
    source = filters.source ?? '';
    author = filters.author ?? '';
    status = filters.status ?? '';
  }
  function syncUrl(filters: DiscoveryFilters) {
    const params = new URLSearchParams();
    for (const key of ['q', 'kind', 'source', 'author', 'status'] as const) {
      const value = filters[key];
      if (value) params.set(key, value);
    }
    const query = params.toString();
    history.pushState(history.state, '', `/commons${query ? `?${query}` : ''}`);
  }
  async function search(filters = appliedFilters, more = false) {
    const generation = ++searchGeneration;
    busy = true;
    error = '';
    try {
      const next = await catalogue.search({
        ...filters,
        cursor: more ? page?.next_cursor : undefined,
      });
      if (generation !== searchGeneration) return;
      page = more && page ? { ...next, items: [...page.items, ...next.items] } : next;
    } catch (cause) {
      if (generation === searchGeneration) error = explain(cause);
    } finally {
      if (generation === searchGeneration) busy = false;
    }
  }
  function commitSearch(filters: DiscoveryFilters) {
    appliedFilters = filters;
    syncUrl(appliedFilters);
    void search(appliedFilters);
  }
  function applySearch() {
    commitSearch(normalizedFilters());
  }
  function resetAdvancedFilters() {
    kind = undefined;
    source = '';
    author = '';
    status = '';
    commitSearch({ q: appliedFilters.q });
  }
  function clearSearch() {
    setDrafts({});
    commitSearch({});
  }
  function removeFilter(filter: 'kind' | 'source' | 'author' | 'status') {
    if (filter === 'kind') kind = undefined;
    else if (filter === 'source') source = '';
    else if (filter === 'author') author = '';
    else status = '';
    commitSearch({ ...appliedFilters, [filter]: undefined });
  }
  async function toggleAdmission() {
    admitting = !admitting;
    if (admitting) {
      await tick();
      admissionHeading?.focus();
    }
  }
  function excerpt(value: string, limit = 220) {
    const text = value
      .replace(/\[([^\]]+)]\([^)]+\)/g, '$1')
      .replace(/[`*_>#~]/g, '')
      .replace(/\s+/g, ' ')
      .trim();
    return text.length > limit ? `${text.slice(0, limit).trimEnd()}…` : text;
  }
  onMount(() => {
    if (entryId || revisionId || publicationId) return;
    const restore = () => {
      appliedFilters = readUrlFilters();
      setDrafts(appliedFilters);
      filtersOpen = countAdvancedFilters(appliedFilters) > 0;
      void search(appliedFilters);
    };
    restore();
    addEventListener('popstate', restore);
    return () => removeEventListener('popstate', restore);
  });
</script>

{#if publicationId}
  {#await import('./PublicPublication.svelte')}<main id="main" class="page" tabindex="-1">
      <LoadingState>Loading public release…</LoadingState>
    </main>
  {:then module}{#key publicationId}<module.default manifestId={publicationId} />{/key}{/await}
{:else if revisionId}
  {#await import('./PublicRecord.svelte')}<main id="main" class="page" tabindex="-1">
      <LoadingState>Loading research…</LoadingState>
    </main>
  {:then module}{#key revisionId}<module.default {revisionId} />{/key}{/await}
{:else if entryId}
  {#await import('./Statement.svelte')}<main id="main" class="page" tabindex="-1">
      <LoadingState>Loading statement…</LoadingState>
    </main>
  {:then module}{#key entryId}<module.default {entryId} />{/key}{/await}
{:else}
  <main id="main" class="page" tabindex="-1">
    <header class="explore-heading">
      <h1>Explore public research</h1>
      <p class="muted">
        Find sourced statements, open questions, proof sketches, and attributable research. Interest
        is not endorsement.
      </p>
      <p><a href="/projects?scope=public">Browse public projects</a></p>
    </header>
    <form
      class="explore-search"
      onsubmit={(event) => {
        event.preventDefault();
        applySearch();
      }}
    >
      <div class="explore-search-row">
        <Field.Label class="explore-query"
          ><span>Search public research</span><Input
            type="search"
            bind:value={q}
            placeholder="Search titles, research content, or sources"
          /></Field.Label
        >
        <Button type="submit" disabled={busy}>Search</Button>
        <Button
          variant="outline"
          class="explore-filter-toggle"
          type="button"
          aria-expanded={filtersOpen}
          aria-controls="explore-filters"
          onclick={() => (filtersOpen = !filtersOpen)}
          >Filters{advancedFilterCount ? ` (${advancedFilterCount})` : ''}</Button
        >
      </div>
      {#if filtersOpen}<fieldset id="explore-filters" class="explore-filters">
          <legend>Filter public research</legend>
          <div class="explore-filter-grid">
            <Field.Label
              >Research type<NativeSelect bind:value={kind}
                ><option value={undefined}>All research types</option
                >{#each kinds as value (value)}<option {value}>{kindLabels[value]}</option
                  >{/each}</NativeSelect
              ></Field.Label
            >
            <Field.Label
              >Source<Input
                bind:value={source}
                placeholder="DOI, arXiv ID, version, or locator"
              /></Field.Label
            >
            <Field.Label
              >Author<Input bind:value={author} placeholder="Name of a contributor" /></Field.Label
            >
            <Field.Label
              >Reported status<Input
                list="reported-statuses"
                bind:value={status}
                placeholder="For example, FAILED"
              /></Field.Label
            >
            <datalist id="reported-statuses">
              {#each ['Open', 'UNASSESSED', 'IN_PROGRESS', 'POTENTIAL', 'PARTIAL', 'COMPLETE', 'SUCCEEDED', 'STALLED', 'FAILED'] as value (value)}<option
                  {value}
                ></option>{/each}
            </datalist>
          </div>
          <div class="explore-filter-actions">
            <Button type="submit" disabled={busy}>Apply filters</Button>
            <Button
              variant="outline"
              class=""
              type="button"
              disabled={busy}
              onclick={resetAdvancedFilters}>Reset filters</Button
            >
          </div>
        </fieldset>{/if}
    </form>
    {#if advancedFilterCount > 0}<div class="explore-applied" aria-label="Applied filters">
        <span>Applied filters</span>
        {#if appliedFilters.kind}<Button
            type="submit"
            class="explore-filter-chip"
            onclick={() => removeFilter('kind')}
            aria-label={`Remove type filter ${kindLabels[appliedFilters.kind!]}`}
            >{kindLabels[appliedFilters.kind!]} <span aria-hidden="true">×</span></Button
          >{/if}
        {#if appliedFilters.source}<Button
            type="submit"
            class="explore-filter-chip"
            onclick={() => removeFilter('source')}
            aria-label={`Remove source filter ${appliedFilters.source}`}
            >Source: {appliedFilters.source} <span aria-hidden="true">×</span></Button
          >{/if}
        {#if appliedFilters.author}<Button
            type="submit"
            class="explore-filter-chip"
            onclick={() => removeFilter('author')}
            aria-label={`Remove author filter ${appliedFilters.author}`}
            >Author: {appliedFilters.author} <span aria-hidden="true">×</span></Button
          >{/if}
        {#if appliedFilters.status}<Button
            type="submit"
            class="explore-filter-chip"
            onclick={() => removeFilter('status')}
            aria-label={`Remove status filter ${appliedFilters.status}`}
            >Status: {appliedFilters.status} <span aria-hidden="true">×</span></Button
          >{/if}
      </div>{/if}
    {#if error}<div class="notice explore-error" role="alert">
        <span>{error}</span>
        <Button type="submit" variant="outline" class="" onclick={() => search(appliedFilters)}
          >Retry</Button
        >
      </div>{/if}
    <div class="explore-results-heading">
      <div>
        <h2>{appliedFilters.q ? `Results for “${appliedFilters.q}”` : 'Public research'}</h2>
      </div>
      {#if auth.signedIn}<Button type="submit" variant="outline" class="" onclick={toggleAdmission}
          >{admitting ? 'Close contribution form' : 'Contribute'}</Button
        >{/if}
    </div>
    {#if admitting}
      <CatalogueAdmissionForm destination="/commons" bind:admissionHeading />
    {/if}
    <section class="explore-results" aria-label="Public research results" aria-busy={busy}>
      {#if busy && !page}<p role="status" class="explore-status">
          Searching public research…
        </p>{:else}
        {#if busy}<p role="status" class="explore-status">Updating results…</p>{/if}
        <div class="explore-result-list">
          {#each page?.items ?? [] as hit (hit.object_version.id)}
            <article class="explore-result">
              <div class="explore-result-meta">
                <Badge variant="outline">{kindLabels[hit.object_version.kind]}</Badge>
                <span>
                  {hit.object_version.authorship.actor_kind === 'AGENT'
                    ? (hit.object_version.authorship.agent_display_name ?? 'Research agent')
                    : (hit.object_version.authorship.author_display_name ?? 'Research contributor')}
                </span>
              </div>
              <h3>
                <a
                  href={hit.catalogue_entry_id
                    ? `/commons/${hit.catalogue_entry_id}`
                    : `/commons/records/${hit.object_version.id}`}
                  >{hit.object_version.content.title}</a
                >
              </h3>
              {#if hit.object_version.content.content_md}<p class="explore-result-excerpt">
                  {excerpt(hit.object_version.content.content_md)}
                </p>{/if}
              <div class="explore-result-details">
                {#if hit.source_identifier}<span
                    >Source: {hit.source_identifier}{hit.source_version
                      ? ` · ${hit.source_version}`
                      : ''}{hit.source_locator ? ` · ${hit.source_locator}` : ''}</span
                  >{/if}
                {#if hit.object_version.content.reported_outcome}<span
                    >Reported outcome: {hit.object_version.content.reported_outcome}</span
                  >{/if}
              </div>
            </article>
          {:else}{#if page}<div class="empty explore-empty">
                <h3>
                  {hasAppliedSearch ? 'No matching public research' : 'No public research yet'}
                </h3>
                <p class="muted">
                  {hasAppliedSearch
                    ? 'Try broader terms or remove one or more filters.'
                    : 'Published research will appear here when it becomes available.'}
                </p>
                {#if hasAppliedSearch}<Button
                    type="submit"
                    variant="outline"
                    class=""
                    onclick={clearSearch}>Clear search and filters</Button
                  >{/if}
              </div>{/if}{/each}
        </div>
        {#if page?.next_cursor}<Button
            type="submit"
            variant="outline"
            class="explore-load-more"
            disabled={busy}
            onclick={() => search(appliedFilters, true)}>Load more research</Button
          >{/if}
      {/if}
    </section>
  </main>
{/if}
