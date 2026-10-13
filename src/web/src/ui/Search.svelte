<script lang="ts">
  import BrandWordmark from './BrandWordmark.svelte';
  import PlannedBadge from './PlannedBadge.svelte';
  import { Search as SearchIcon, X } from '@lucide/svelte';
  import HomepageContent from './HomepageContent.svelte';
  import DiscoveryState from './DiscoveryState.svelte';
  import LoadingState from './LoadingState.svelte';
  import HighlightedText from './HighlightedText.svelte';
  import SearchExcerpt from './SearchExcerpt.svelte';
  import { searchQuery, type NavigateQuery, type readSearch } from '../lib/ui-location';
  import { tick, untrack } from 'svelte';
  import { projectContext, explain } from '../svelte-lib/context';
  import type { components } from '$lib/api-client';
  import type { PublicProject } from '../lib/research-api';
  import { Button } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';

  let {
    query = '',
    resultType = 'all',
    onNavigate,
  }: {
    query?: string;
    resultType?: ReturnType<typeof readSearch>['type'];
    onNavigate?: NavigateQuery;
  } = $props();
  const { catalogue, api } = projectContext();
  let draft = $state('');
  let searchInput = $state<HTMLInputElement | null>(null);
  async function clearSearch() {
    draft = '';
    if (onNavigate) onNavigate('');
    else location.assign('/');
    await tick();
    searchInput?.focus();
  }
  let research = $state<components['schemas']['VersionDiscoveryHit'][]>([]);
  let projects = $state<PublicProject[]>([]);
  let researchCursor = $state<string | null>();
  let projectCursor = $state<string>();
  let researchBusy = $state(false);
  let projectBusy = $state(false);
  let researchError = $state('');
  let projectError = $state('');
  let generation = 0;
  const term = $derived(query.trim());
  const invalid = $derived(term.length > 200);

  function message(cause: unknown) {
    return (cause as { status?: number })?.status === 404
      ? '404 — Search not found.'
      : explain(cause);
  }

  async function loadResearch(more = false) {
    const request = generation;
    researchBusy = true;
    researchError = '';
    try {
      const page = await catalogue.search({
        q: term,
        cursor: more ? (researchCursor ?? undefined) : undefined,
      });
      if (request !== generation) return;
      research = more ? [...research, ...page.items] : page.items;
      researchCursor = page.next_cursor;
    } catch (cause) {
      if (request === generation) researchError = message(cause);
    } finally {
      if (request === generation) researchBusy = false;
    }
  }

  async function loadProjects(more = false) {
    const request = generation;
    projectBusy = true;
    projectError = '';
    try {
      const page = await api.listPublicProjects(term, more ? projectCursor : undefined);
      if (request !== generation) return;
      projects = more ? [...projects, ...page.items] : page.items;
      projectCursor = page.nextCursor;
    } catch (cause) {
      if (request === generation) projectError = message(cause);
    } finally {
      if (request === generation) projectBusy = false;
    }
  }

  $effect(() => {
    const nextQuery = query;
    untrack(() => {
      generation += 1;
      draft = nextQuery;
      research = [];
      projects = [];
      researchCursor = undefined;
      projectCursor = undefined;
      researchError = '';
      projectError = '';
      researchBusy = false;
      projectBusy = false;
      if (term && !invalid) {
        void loadResearch();
        void loadProjects();
      }
    });
    return () => {
      generation += 1;
    };
  });
</script>

<main id="main" class="page discovery-page search-page" tabindex="-1">
  <section class="home-search" class:has-query={Boolean(term)} aria-label="Search and tools">
    <h1>
      <img
        class="home-brand-mark"
        src="/brand/polycolab-mark.png"
        alt=""
        aria-hidden="true"
      /><BrandWordmark />
    </h1>
    <form
      role="search"
      action="/"
      method="GET"
      onsubmit={(event) => {
        if (onNavigate) {
          event.preventDefault();
          onNavigate(searchQuery(draft, resultType));
        }
      }}
    >
      <input type="hidden" name="type" value={resultType} />
      <label class="sr-only" for="research-search">Search public research and projects</label>
      <div class="search-controls">
        <Input
          id="research-search"
          bind:ref={searchInput}
          type="search"
          name="q"
          bind:value={draft}
          maxlength={200}
          required
          placeholder="Search public research and projects"
          class="home-search-input"
        />
        {#if draft || term}<Button
            type="button"
            variant="ghost"
            aria-label="Clear search"
            class="home-search-submit"
            onclick={clearSearch}><X size={18} aria-hidden="true" /></Button
          >{/if}
        <Button type="submit" variant="ghost" aria-label="Search" class="home-search-submit"
          ><SearchIcon size={20} aria-hidden="true" /></Button
        >
      </div>
    </form>
    {#if !term}<nav class="home-actions" aria-label="Ways to use Polycolab">
        <Button href="/docs/getting-started/" data-sveltekit-reload>Getting started</Button>
        <Button href="/chat" variant="outline">Chat with built-in agent <PlannedBadge /></Button>
        <Button href="/SKILL.md" data-sveltekit-reload variant="outline">SKILL.md</Button>
      </nav>{/if}
  </section>
  {#if invalid}<p role="alert">Enter at most 200 characters.</p>
  {:else if !term}<div class="homepage-secondary"><HomepageContent /></div>
  {:else}
    <nav class="search-types" aria-label="Search result types">
      {#each [['all', 'All'], ['research', 'Research'], ['projects', 'Projects']] as [value, label] (value)}<a
          href={`/?${searchQuery(term, value as typeof resultType)}`}
          data-sveltekit-noscroll
          data-sveltekit-keepfocus
          aria-current={resultType === value ? 'page' : undefined}>{label}</a
        >{/each}
    </nav>
    <p>Results for “{term}”</p>
    <p class="sr-only" role="status">
      {researchBusy || projectBusy
        ? 'Searching…'
        : `${research.length} research results and ${projects.length} projects loaded.`}
    </p>
    {#if resultType !== 'projects'}<section aria-label="Research results" aria-busy={researchBusy}>
        <h2>Research</h2>
        {#if researchError}<DiscoveryState
            kind="error"
            level="h3"
            title="Could not search research"
            description={researchError}
          >
            <Button
              variant="outline"
              disabled={researchBusy}
              onclick={() => loadResearch(Boolean(research.length))}>Retry research search</Button
            ></DiscoveryState
          >{/if}
        {#if researchBusy}<LoadingState>Searching research…</LoadingState>{/if}
        <ul class="list">
          {#each research as hit (hit.object_version.id)}
            <li>
              <h3>
                <a
                  href={hit.catalogue_entry_id
                    ? `/library/${hit.catalogue_entry_id}`
                    : `/commons/records/${hit.object_version.id}`}
                  ><HighlightedText text={hit.object_version.content.title} query={term} /></a
                >
              </h3>
              <p>
                {hit.catalogue_entry_id ? 'Library statement' : 'Research record'} · {hit
                  .object_version.kind} ·
                {hit.object_version.authorship.actor_kind === 'AGENT' ? 'Agent' : 'Human'}: {hit
                  .object_version.authorship.agent_display_name ??
                  hit.object_version.authorship.author_display_name ??
                  'Research contributor'}
              </p>
              <SearchExcerpt content={hit.object_version.content.content_md} query={term} />
            </li>
          {/each}
        </ul>
        {#if !researchBusy && !researchError && !research.length}<DiscoveryState
            level="h3"
            title="No matching research"
            description="Try different words or a broader search."
          />{/if}
        {#if researchCursor}<Button
            variant="outline"
            disabled={researchBusy}
            onclick={() => loadResearch(true)}>Load more research</Button
          >{/if}
      </section>
    {/if}
    {#if resultType !== 'research'}<section aria-label="Project results" aria-busy={projectBusy}>
        <h2>Projects</h2>
        {#if projectError}<DiscoveryState
            kind="error"
            level="h3"
            title="Could not search project"
            description={projectError}
          >
            <Button variant="outline" onclick={() => loadProjects(Boolean(projects.length))}
              >Retry project search</Button
            ></DiscoveryState
          >{/if}
        {#if projectBusy}<LoadingState>Searching projects…</LoadingState>{/if}
        <ul class="list">
          {#each projects as project (project.id)}
            <li>
              <h3>
                <a href={`/projects/${project.id}`}
                  ><HighlightedText text={project.name} query={term} /></a
                >
              </h3>
              <p><HighlightedText text={project.description ?? ''} query={term} /></p>
            </li>
          {/each}
        </ul>
        {#if !projectBusy && !projectError && !projects.length}<DiscoveryState
            level="h3"
            title="No matching projects"
            description="Try different words or a broader search."
          />{/if}
        {#if projectCursor}<Button
            variant="outline"
            disabled={projectBusy}
            onclick={() => loadProjects(true)}>Load more projects</Button
          >{/if}
      </section>{/if}
  {/if}
</main>

<style>
  .search-types {
    display: flex;
    gap: 1.25rem;
    flex-wrap: wrap;
  }
  .search-types {
    border-bottom: 1px solid var(--line);
  }
  .search-types a {
    padding: 0.6rem 0.1rem;
  }
  .search-types a[aria-current] {
    border-bottom: 2px solid var(--brand);
    color: var(--brand);
    font-weight: 600;
  }

  section,
  form {
    display: grid;
    gap: 1rem;
  }
  .home-search {
    min-height: min(680px, calc(100svh - 96px));
    display: grid;
    align-content: center;
    justify-items: center;
    gap: 32px;
    padding: 48px 0 80px;
  }
  h1 {
    display: flex;
    align-items: center;
    gap: 0.2em;
    margin: 0;
    font-size: clamp(44px, 6vw, 72px);
    line-height: 1.15;
  }
  .home-brand-mark {
    width: 1.1em;
    height: 1.1em;
    object-fit: contain;
    flex-shrink: 0;
  }
  .home-search form {
    width: min(100%, 680px);
  }
  .search-controls {
    display: flex;
    align-items: center;
    min-width: 0;
    padding: 5px 6px 5px 16px;
    border: 1px solid var(--line);
    border-radius: 999px;
    box-shadow: 0 2px 8px #00000008;
  }
  .search-controls:focus-within {
    border-color: var(--brand);
    box-shadow: 0 0 0 2px var(--brand-soft);
  }
  .search-controls :global(.home-search-input) {
    flex: 1;
    min-width: 0;
    height: 44px;
    padding-inline: 0;
    border: 0;
    background: transparent;
    box-shadow: none;
    outline: none;
    font-size: 16px;
  }
  .search-controls :global(.home-search-submit) {
    flex-shrink: 0;
    width: 44px;
    height: 44px;
    border-radius: 50%;
  }
  .home-actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 12px;
  }
  .home-actions :global(a) {
    min-height: 40px;
    padding-inline: 16px;
  }
  .homepage-secondary {
    display: grid;
    gap: 64px;
    padding-top: 48px;
    border-top: 1px solid var(--line);
  }
  .home-search.has-query {
    min-height: 0;
    padding: 8px 0 24px;
    gap: 20px;
  }
  .has-query h1 {
    font-size: 32px;
  }
  @media (max-width: 700px) {
    .home-search {
      gap: 24px;
      padding: 32px 0 64px;
    }
    .home-actions {
      gap: 10px;
    }
    .home-actions :global(a) {
      min-height: 44px;
    }
    .homepage-secondary {
      gap: 48px;
      padding-top: 32px;
    }
    .search-controls :global(.home-search-input) {
      font-size: 14px;
    }
  }
</style>
