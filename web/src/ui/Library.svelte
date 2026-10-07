<script lang="ts">
  import { relationshipEndpoints } from '../lib/relationship-view';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import * as Field from '../lib/components/ui/field';
  import { onMount } from 'svelte';
  import type { CatalogueEntry, CatalogueRevision, LibraryFilters } from '../lib/catalogue-api';
  import { workspace, explain } from '../svelte-lib/context';
  import { accountHref } from '../lib/account-navigation';
  import Markdown from './Markdown.svelte';
  import LoadingState from './LoadingState.svelte';
  import DiscoveryState from './DiscoveryState.svelte';
  import LibraryBasis from './LibraryBasis.svelte';
  import LibraryImport from './LibraryImport.svelte';
  import FormulationFields from './FormulationFields.svelte';
  import CatalogueEdit from './CatalogueEdit.svelte';
  let { entryId, revisionId }: { entryId?: string; revisionId?: string } = $props();
  const basePath = '/library';
  const { catalogue, records, auth } = workspace();
  let page = $state<Awaited<ReturnType<typeof catalogue.library>>>();
  let entry = $state<CatalogueEntry>();
  let history = $state<Awaited<ReturnType<typeof catalogue.history>>>();
  let relations = $state<Awaited<ReturnType<typeof records.relations>>>([]);
  let relationCursor = $state<string | null>(null);
  let relationTitles = $state<Record<string, string>>({});
  let q = $state('');
  let kind = $state<LibraryFilters['kind']>();
  let status = $state('');
  let basis = $state<LibraryFilters['basis']>();
  let source = $state('');
  let filtersOpen = $state(false);
  let applied = $state<LibraryFilters>({});
  let busy = $state(false);
  let error = $state('');
  let copied = $state(false);
  let preview = $state(false);
  let saving = $state(false);
  let saveError = $state('');
  let admissionKind = $state<'STATEMENT' | 'PROBLEM' | 'DEFINITION'>('STATEMENT');
  let draft = $state<CatalogueRevision>({
    expected_current_object_version_id: '',
    title: '',
    content_md: '',
    assumptions_md: '',
    source: { identifier: '', version: '', locator: '' },
    reported_status: 'Open',
    reason: 'Initial Library admission',
  });
  let receipt: { body: string; key: string } | undefined;
  let generation = 0;
  const filters = ['kind', 'status', 'basis', 'source'] as const;
  const labels: Record<string, string> = {
    STATEMENT: 'Statement',
    PROBLEM: 'Question',
    DEFINITION: 'Definition',
  };
  function filterLabel(field: (typeof filters)[number]) {
    if (field === 'kind') return labels[applied.kind!];
    if (field === 'basis')
      return applied.basis === 'review' ? 'Human-reviewed' : 'Literature-backed';
    return applied[field];
  }
  function restore() {
    const params = new URL(location.href).searchParams;
    q = params.get('q') || '';
    const requested = params.get('kind');
    kind =
      requested === 'STATEMENT' || requested === 'PROBLEM' || requested === 'DEFINITION'
        ? requested
        : undefined;
    status = params.get('status') || '';
    const requestedBasis = params.get('basis');
    basis =
      requestedBasis === 'literature' || requestedBasis === 'review' ? requestedBasis : undefined;
    source = params.get('source') || '';
    applied = { q, kind, status: status || undefined, basis, source: source || undefined };
    void search();
  }
  function apply() {
    applied = {
      q: q.trim() || undefined,
      kind,
      status: status || undefined,
      basis,
      source: source.trim() || undefined,
    };
    const params = new URLSearchParams();
    for (const field of ['q', ...filters] as const)
      if (applied[field]) params.set(field, applied[field]!);
    window.history.pushState(
      window.history.state,
      '',
      `${basePath}${params.size ? `?${params}` : ''}`,
    );
    void search();
  }
  function clear() {
    q = '';
    kind = undefined;
    status = '';
    basis = undefined;
    source = '';
    apply();
  }
  function remove(field: (typeof filters)[number]) {
    q = applied.q || '';
    kind = applied.kind;
    status = applied.status || '';
    basis = applied.basis;
    source = applied.source || '';
    if (field === 'kind') kind = undefined;
    if (field === 'status') status = '';
    if (field === 'basis') basis = undefined;
    if (field === 'source') source = '';
    apply();
  }
  async function search(more = false) {
    const current = ++generation;
    busy = true;
    error = '';
    try {
      const next = await catalogue.library({
        ...applied,
        cursor: more ? page?.next_cursor : undefined,
      });
      if (current === generation)
        page = more && page ? { ...next, items: [...page.items, ...next.items] } : next;
    } catch (cause) {
      if (current === generation) error = explain(cause);
    } finally {
      if (current === generation) busy = false;
    }
  }
  async function loadEntry() {
    if (!entryId) return;
    busy = true;
    error = '';
    try {
      entry = revisionId
        ? await catalogue.revision(entryId, revisionId)
        : await catalogue.get(entryId);
      history = await catalogue.history(entryId);
      await loadRelations();
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function loadRelations(more = false) {
    if (!entry) return;
    const page = await records.relationPage(
      entry.object_version.id,
      more ? (relationCursor ?? undefined) : undefined,
    );
    relations = more ? [...relations, ...page.items] : page.items;
    relationCursor = page.next_cursor;
    const ids = [
      ...new Set(
        page.items.map((relation) =>
          relationshipEndpoints(relation)[0] === entry!.object_version.id
            ? relationshipEndpoints(relation)[1]
            : relationshipEndpoints(relation)[0],
        ),
      ),
    ];
    const titles = await Promise.allSettled(ids.map((id) => records.get(id)));
    for (let index = 0; index < titles.length; index += 1) {
      const title = titles[index]!;
      if (title.status === 'fulfilled') relationTitles[ids[index]!] = title.value.content.title;
    }
  }
  async function moreRelations() {
    busy = true;
    error = '';
    try {
      await loadRelations(true);
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function moreHistory() {
    if (!entryId || !history?.next_cursor) return;
    busy = true;
    try {
      const next = await catalogue.history(entryId, history.next_cursor);
      history = { ...next, items: [...history.items, ...next.items] };
    } catch (cause) {
      error = explain(cause);
    } finally {
      busy = false;
    }
  }
  async function copy() {
    if (!entry) return;
    try {
      await navigator.clipboard.writeText(
        `${location.origin}/library/${entry.entry_id}/revisions/${entry.object_version.id}`,
      );
      copied = true;
    } catch {
      error = 'Could not copy the link. Open the exact version link and copy its address.';
    }
  }
  async function admit() {
    saving = true;
    saveError = '';
    try {
      const { expected_current_object_version_id: ignored, ...formulation } = draft;
      void ignored;
      const body = { ...formulation, kind: admissionKind };
      const serialized = JSON.stringify(body);
      if (receipt?.body !== serialized) receipt = { body: serialized, key: crypto.randomUUID() };
      const result = await catalogue.admit(body, receipt.key);
      window.location.assign(`/library/${result.entry_id}`);
    } catch (cause) {
      saveError = explain(cause);
    } finally {
      saving = false;
    }
  }
  onMount(() => {
    if (entryId === 'new') return;
    if (entryId) {
      void loadEntry();
      return;
    }
    restore();
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  });
</script>

<svelte:head
  ><title
    >{entryId === 'new' ? 'Add to Library' : (entry?.object_version.content.title ?? 'Library')} · Polycolab</title
  ></svelte:head
>

<main id="main" class="page library-page discovery-page" tabindex="-1">
  {#if entryId === 'new'}
    <p><a href={basePath}>← Library</a></p>
    <header class="discovery-heading">
      <h1>Add to Library</h1>
      <p>Add a statement, question or definition supported by literature or your human review.</p>
    </header>
    {#if !auth.loaded}<LoadingState>Checking account…</LoadingState>
    {:else if auth.signedIn}
      <section id="library-admission" class="panel">
        <h2>{preview ? 'Preview Library entry' : 'Add a statement or question'}</h2>
        {#if preview}<h3>{draft.title}</h3>
          <p>{labels[admissionKind]} · {draft.reported_status}</p>
          <Markdown content={draft.content_md} />
          <h3>Assumptions</h3>
          <Markdown content={draft.assumptions_md} />{#if draft.source}<p>
              Literature: {draft.source.identifier} · {draft.source.version} · {draft.source
                .locator}
            </p>{/if}{#if draft.review_rationale}<h3>Your review</h3>
            <Markdown content={draft.review_rationale} />{/if}
          <p>This entry and your attribution will be public.</p>
          <div class="row">
            <Button disabled={saving} onclick={admit}
              >{saving ? 'Saving…' : 'Add to Library'}</Button
            ><Button variant="outline" disabled={saving} onclick={() => (preview = false)}
              >Back to editing</Button
            >
          </div>
        {:else}<form
            onsubmit={(event) => {
              event.preventDefault();
              preview = true;
            }}
          >
            <Field.Label
              >Object type<NativeSelect bind:value={admissionKind}
                >{#each ['STATEMENT', 'PROBLEM', 'DEFINITION'] as value (value)}<option {value}
                    >{labels[value as keyof typeof labels]}</option
                  >{/each}</NativeSelect
              ></Field.Label
            ><FormulationFields bind:draft /><Button type="submit">Preview entry</Button>
          </form>{/if}
        {#if saveError}<p role="alert">{saveError}</p>{/if}
      </section>
    {:else}<p>Sign in to add to Library.</p>
      <Button href={accountHref('signin', '/library/new')}>Sign in</Button>{/if}
  {:else if entryId}
    <a href={basePath}>← Library</a>
    {#if busy && !entry}<LoadingState>Loading statement…</LoadingState>{/if}
    {#if error}<DiscoveryState kind="error" title="Could not load Library" description={error}
        ><Button onclick={loadEntry}>Retry</Button></DiscoveryState
      >{/if}
    {#if entry}
      <header class="discovery-heading library-entry-heading">
        <p class="eyebrow">
          {labels[entry.object_version.kind] ?? entry.object_version.kind} · Version {entry
            .object_version.number}
        </p>
        <h1>{entry.object_version.content.title}</h1>
        <LibraryBasis {entry} />
        <div class="row">
          <LibraryImport {entry} /><Button variant="outline" onclick={copy}
            >{copied ? 'Link copied' : 'Copy version link'}</Button
          >
        </div>
      </header>
      {#if revisionId}<p class="notice">
          You are reading an exact version. <a href={`/library/${entry.entry_id}`}
            >View current Library entry</a
          >
        </p>{/if}
      <article class="panel library-formulation">
        <h2>Statement</h2>
        <Markdown content={entry.object_version.content.content_md} />
        <h2>Assumptions</h2>
        <Markdown content={entry.object_version.content.assumptions_md} />
      </article>
      <section class="panel">
        <h2>Status and supporting basis</h2>
        <LibraryBasis {entry} detailed />
        <p class="muted">
          This records literature or human judgment about the statement’s status. It is not a
          machine proof check.
        </p>
      </section>
      <section class="panel">
        <h2>Related statements and research</h2>
        {#each relations as relation (relation.id)}{@const relatedRevision =
            relationshipEndpoints(relation)[0] === entry.object_version.id
              ? relationshipEndpoints(relation)[1]
              : relationshipEndpoints(relation)[0]}
          <p>
            <a href={`/commons/records/${relatedRevision}`}
              >{relationTitles[relatedRevision] || 'Related research'}</a
            >
            · {relation.relationship_type.replaceAll('_', ' ').toLowerCase()} · {relation.description}
          </p>{:else}<p class="muted">
            No linked research yet. Import this statement to start an investigation.
          </p>{/each}
        {#if relationCursor}<Button variant="outline" disabled={busy} onclick={moreRelations}
            >Load more relationships</Button
          >{/if}
      </section>
      <section class="panel">
        <h2>Version history</h2>
        {#each history?.items ?? [] as version (version.object_version.id)}<p>
            <a href={`/library/${entry.entry_id}/revisions/${version.object_version.id}`}
              >Version {version.object_version.number}: {version.object_version.content.title}</a
            >
            · {version.reported_status} · {version.object_version.authorship.author_display_name ||
              'Researcher'}
          </p>{/each}{#if history?.next_cursor}<Button
            variant="outline"
            disabled={busy}
            onclick={moreHistory}>Load more versions</Button
          >{/if}
      </section>
      {#if auth.signedIn && !revisionId}<CatalogueEdit {entry} />{/if}
    {/if}
  {:else}
    <header class="discovery-heading">
      <div class="discovery-title library-index-title">
        <h1>Library</h1>
        {#if auth.signedIn}<Button href="/library/new">Add to Library</Button>{/if}
      </div>
      <p>Find statements and questions to develop in your workspace.</p>
    </header>
    <form
      class="library-search"
      role="search"
      aria-label="Library"
      onsubmit={(event) => {
        event.preventDefault();
        apply();
      }}
    >
      <div class="toolbar library-toolbar">
        <div class="grow library-query">
          <Input
            aria-label="Search Library"
            type="search"
            bind:value={q}
            placeholder="Search statements, assumptions, or literature"
            maxlength={500}
          />
        </div>
        <Button type="submit" disabled={busy}>Search</Button><Button
          type="button"
          variant="outline"
          aria-expanded={filtersOpen}
          aria-controls="library-filters"
          onclick={() => (filtersOpen = !filtersOpen)}>Filters</Button
        >
      </div>
      {#if filtersOpen}<div id="library-filters" class="panel">
          <div class="library-filters">
            <Field.Label
              >Type<NativeSelect bind:value={kind}
                ><option value={undefined}>All types</option><option value="STATEMENT"
                  >Statements</option
                ><option value="PROBLEM">Questions</option><option value="DEFINITION"
                  >Definitions</option
                ></NativeSelect
              ></Field.Label
            >
            <Field.Label
              >Status<NativeSelect bind:value={status}
                ><option value="">All statuses</option
                >{#if status && !['Established', 'Conjectured', 'Open', 'Disproved', 'Definition'].includes(status)}<option
                    value={status}>Legacy status: {status}</option
                  >{/if}{#each ['Established', 'Conjectured', 'Open', 'Disproved', 'Definition'] as value (value)}<option
                    >{value}</option
                  >{/each}</NativeSelect
              ></Field.Label
            >
            <Field.Label
              >Status basis<NativeSelect bind:value={basis}
                ><option value={undefined}>Any basis</option><option value="literature"
                  >Literature-backed</option
                ><option value="review">Human-reviewed</option></NativeSelect
              ></Field.Label
            >
            <Field.Label
              >Source<Input
                bind:value={source}
                placeholder="Book, DOI, arXiv ID…"
                maxlength={500}
              /></Field.Label
            >
          </div>
          <div class="row library-filter-actions">
            <Button variant="outline" disabled={busy}>Apply filters</Button><Button
              type="button"
              variant="outline"
              onclick={clear}>Reset</Button
            >
          </div>
        </div>{/if}
    </form>
    {#if filters.some((field) => applied[field])}<div class="row library-applied">
        {#each filters as field (field)}{#if applied[field]}<Button
              variant="outline"
              size="sm"
              onclick={() => remove(field)}
              aria-label={`Remove ${field} filter`}>{filterLabel(field)} ×</Button
            >{/if}{/each}
      </div>{/if}
    <div class="library-results-heading">
      <h2>{applied.q ? `Results for “${applied.q}”` : 'Explore the Library'}</h2>
      <div class="row">
        <span class="muted">Recently updated</span>
      </div>
    </div>
    {#if error}<DiscoveryState kind="error" title="Could not load Library" description={error}
        ><Button onclick={() => search()}>Retry</Button></DiscoveryState
      >{/if}
    {#if busy}<LoadingState>{page ? 'Updating results…' : 'Loading Library…'}</LoadingState>{/if}
    <section class="library-results" aria-label="Library entries" aria-busy={busy}>
      {#if page?.items.length}
        <table class="library-table">
          <caption class="sr-only">Library entries, most recently updated first</caption>
          <thead
            ><tr
              ><th scope="col">Entry</th><th scope="col" class="status-column">Status</th><th
                scope="col"
                class="updated-column">Updated</th
              ></tr
            ></thead
          >
          <tbody
            >{#each page.items as item (item.entry_id)}{@const updated =
                item.object_version.created_at}
              <tr>
                <td class="entry-column">
                  <a class="entry-link" href={`${basePath}/${item.entry_id}`}
                    >{item.object_version.content.title}</a
                  >
                  <span class="entry-type"
                    >{labels[item.object_version.kind] ?? item.object_version.kind}</span
                  >
                </td>
                <td class="status-column"
                  ><span class="entry-status">{item.reported_status}</span></td
                >
                <td class="updated-column"
                  ><time datetime={updated} title={new Date(updated).toLocaleString()}
                    >{new Date(updated).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}</time
                  ></td
                >
              </tr>
            {/each}</tbody
          >
        </table>
      {:else}{#if page && !busy && !error}<DiscoveryState
            level="h3"
            title={Object.values(applied).some(Boolean)
              ? 'No matching entries'
              : 'The Library is ready for its first entry'}
            description={Object.values(applied).some(Boolean)
              ? 'Try broader terms or remove a filter.'
              : 'Add a statement or question with a literature reference or an attributable human review.'}
          >
            {#if Object.values(applied).some(Boolean)}<Button variant="outline" onclick={clear}
                >Clear search and filters</Button
              >
            {:else}<Button href="/workspaces?scope=public" variant="outline"
                >Explore public workspaces</Button
              >{/if}
          </DiscoveryState>{/if}{/if}
    </section>
    {#if page?.next_cursor}<div class="row">
        <Button variant="outline" disabled={busy} onclick={() => search(true)}
          >Load more entries</Button
        >
      </div>{/if}
  {/if}
</main>

<style>
  .library-index-title {
    justify-content: space-between;
  }
  .library-search {
    display: grid;
    gap: 16px;
  }
  .library-toolbar {
    margin: 0;
    padding: 0;
    gap: 8px;
    align-items: center;
  }
  .library-toolbar :global(.library-query) {
    flex: 1;
    min-width: 220px;
  }
  .library-filters {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
  }
  .library-filter-actions {
    margin-top: 16px;
  }
  .library-results-heading {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }
  .library-results-heading h2 {
    margin: 0;
    font-size: 20px;
  }
  .library-results {
    display: grid;
    gap: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .library-table {
    width: 100%;
    table-layout: fixed;
    border-collapse: collapse;
    text-align: left;
  }
  .library-table th {
    padding: 10px 16px;
    background: var(--muted);
    color: var(--muted-foreground);
    font-size: 12px;
    font-weight: 500;
  }
  .library-table td {
    padding: 10px 16px;
    border-top: 1px solid var(--border);
    vertical-align: middle;
  }
  .library-table tbody tr:hover,
  .library-table tbody tr:focus-within {
    background: color-mix(in srgb, var(--muted) 60%, transparent);
  }
  .entry-link {
    display: block;
    font-size: 14px;
    line-height: 1.4;
    font-weight: 550;
    color: var(--foreground);
    overflow-wrap: anywhere;
  }
  .entry-link:hover {
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .entry-link:focus-visible {
    outline: 2px solid var(--brand);
    outline-offset: 3px;
    border-radius: 2px;
  }
  .entry-type {
    display: block;
    margin-top: 3px;
    color: var(--muted-foreground);
    font-size: 11px;
    line-height: 1.3;
  }
  .status-column {
    width: 135px;
  }
  .entry-status {
    display: inline-block;
    max-width: 100%;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 11px;
    line-height: 1.4;
    overflow-wrap: anywhere;
  }
  .updated-column {
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .updated-column {
    width: 132px;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .library-page {
    gap: 16px;
  }
  .library-entry-heading {
    overflow-wrap: anywhere;
  }
  .library-formulation {
    min-width: 0;
  }
  @media (max-width: 700px) {
    .library-filters {
      grid-template-columns: 1fr;
    }
    .library-toolbar :global(.library-query) {
      flex-basis: 100%;
      min-width: 0;
    }
    .library-table th,
    .library-table td {
      padding: 10px 12px;
    }
    .updated-column {
      display: none;
    }
    .status-column {
      width: 100px;
      text-align: right;
    }
  }
</style>
