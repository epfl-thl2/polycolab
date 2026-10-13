<script lang="ts">
  import type { Page, Project, PublicProject } from '../lib/research-api';
  type ProjectListingItem = PublicProject &
    Partial<Pick<Project, 'current_user_role' | 'member_count'>>;
  import { FolderOpen, Globe, LockKeyhole, Users, X, LoaderCircle } from '@lucide/svelte';
  import DiscoveryState from './DiscoveryState.svelte';
  import LoadingState from './LoadingState.svelte';
  import * as Field from '../lib/components/ui/field';
  import * as Alert from '../lib/components/ui/alert';
  import { onMount } from 'svelte';
  import { Button, buttonVariants } from '../lib/components/ui/button';
  import { Input } from '../lib/components/ui/input';
  import { Textarea } from '../lib/components/ui/textarea';
  import { NativeSelect } from '../lib/components/ui/native-select';
  import { toStore } from 'svelte/store';
  import { createQuery, type CreateQueryOptions } from '@tanstack/svelte-query';
  import * as Dialog from '../lib/components/ui/dialog';
  import { goto } from '$app/navigation';
  import { accountHref } from '../lib/account-navigation';
  import { projectContext, explain } from '../svelte-lib/context';
  let { publicScope = false }: { publicScope?: boolean } = $props();
  type ProjectPage = Page<ProjectListingItem> & { pageIndex: number; search: string };
  const basePath = '/projects';
  const { api, query, auth } = projectContext();
  let search = $state('');
  let visibility = $state<'PUBLIC' | 'PRIVATE'>('PUBLIC');
  let searchDraft = $state('');
  let searchInput = $state<HTMLInputElement | null>(null);
  type Category = 'active' | 'owned' | 'shared' | 'archived';
  let category = $state<Category>('active');
  type Sort = 'updated' | 'name' | 'name_desc' | 'relevance';
  let sort = $state<Sort>('updated');
  let resultsHeading = $state<HTMLDivElement>();
  let scrollToResults = $state(false);
  let cursors = $state<(string | undefined)[]>([undefined]);
  let pageIndex = $state(0);
  const pageSize = 20;
  const projects = createQuery(
    toStore<CreateQueryOptions<ProjectPage>>(() => ({
      queryKey: [
        publicScope ? 'public-projects' : 'projects',
        publicScope,
        search,
        sort,
        publicScope ? undefined : category,
        cursors[pageIndex],
      ],
      enabled: publicScope || auth.signedIn,
      placeholderData: (previousData, previousQuery) =>
        previousQuery?.queryKey[1] === publicScope ? previousData : undefined,
      queryFn: async (): Promise<ProjectPage> => {
        const requestedPage = pageIndex;
        const requestedSearch = search;
        const result = await (publicScope
          ? api.listPublicProjects(search, cursors[pageIndex], sort)
          : api.listProjects(cursors[pageIndex], search, category, sort));
        return { ...result, pageIndex: requestedPage, search: requestedSearch };
      },
    })),
  );
  let open = $state(false);
  let name = $state('');
  let description = $state('');
  let busy = $state(false);
  let error = $state('');
  const items = $derived($projects.data?.items ?? []);
  const displayedPage = $derived($projects.data?.pageIndex ?? 0);
  const displayedSearch = $derived($projects.data?.search ?? search);
  const updating = $derived($projects.isFetching && !!$projects.data);
  function resetPage() {
    cursors = [undefined];
    pageIndex = 0;
  }
  $effect(() => {
    void publicScope;
    resetPage();
  });
  $effect(() => {
    if (scrollToResults && $projects.isSuccess && !$projects.isFetching) {
      resultsHeading?.scrollIntoView({
        block: 'start',
        behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
      });
      resultsHeading?.focus({ preventScroll: true });
      scrollToResults = false;
    }
  });
  function changePage(index: number) {
    pageIndex = index;
    scrollToResults = true;
  }
  function chooseSort() {
    resetPage();
    syncUrl();
  }
  function directoryHref(scope: boolean) {
    const params = new URLSearchParams();
    params.set('scope', scope ? 'public' : 'member');
    if (search) params.set('q', search);
    if (sort !== 'updated') params.set('sort', sort);
    if (category !== 'active') params.set('category', category);
    return `${basePath}${params.size ? `?${params}` : ''}`;
  }
  function syncUrl() {
    history.replaceState(history.state, '', directoryHref(publicScope));
  }
  function chooseCategory(value: string) {
    category = value as Category;
    resetPage();
    syncUrl();
  }
  function submitSearch() {
    search = searchDraft.trim();
    sort = search ? 'relevance' : 'updated';
    resetPage();
    syncUrl();
  }
  function clearSearch() {
    search = '';
    searchDraft = '';
    searchInput?.focus();
    if (sort === 'relevance') sort = 'updated';
    resetPage();
    syncUrl();
  }
  onMount(() => {
    const params = new URL(location.href).searchParams;
    search = searchDraft = params.get('q') ?? '';
    const order = params.get('sort');
    if (order && ['updated', 'name', 'name_desc', 'relevance'].includes(order))
      sort = order as Sort;
    const value = params.get('category');
    if (value && ['active', 'owned', 'shared', 'archived'].includes(value))
      category = value as Category;
    resetPage();
  });
  async function create(event: SubmitEvent) {
    event.preventDefault();
    busy = true;
    error = '';
    try {
      const project = await api.createProject({
        name: name.trim(),
        description,
        visibility: visibility,
      });
      await query.invalidateQueries({ queryKey: ['projects'] });
      await query.invalidateQueries({ queryKey: ['public-projects'] });
      open = false;
      await goto(`/projects/${project.id}`);
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
</script>

<main id="main" class="page discovery-page project-page" tabindex="-1">
  <header class="discovery-heading">
    <div class="discovery-title project-title">
      <h1>Projects</h1>
      {#if auth.signedIn}
        <Dialog.Root bind:open
          ><Dialog.Trigger class={buttonVariants()}>New project</Dialog.Trigger><Dialog.Content
            class="sm:max-w-lg"
            ><Dialog.Header class="pr-8"
              ><Dialog.Title class="leading-snug">What are you investigating?</Dialog.Title
              ><Dialog.Description
                >Choose who can view this project. Members can contribute according to their role.</Dialog.Description
              ></Dialog.Header
            >
            <form onsubmit={create}>
              <Field.Label
                >Project name<Input required maxlength={200} bind:value={name} /></Field.Label
              ><Field.Label>Description<Textarea bind:value={description}></Textarea></Field.Label>
              <Field.Label
                >Visibility<NativeSelect bind:value={visibility}>
                  <option value="PUBLIC">Public</option>
                  <option value="PRIVATE">Private</option>
                </NativeSelect></Field.Label
              >
              <p>
                {visibility === 'PUBLIC'
                  ? 'Anyone can view this project and its research.'
                  : 'Only members can view this project and its research.'}
              </p>
              {#if error}<Alert.Root variant="destructive" role="alert">
                  {error}
                </Alert.Root>{/if}
              <div class="row">
                <Button type="submit" disabled={busy || !name.trim()}
                  >{busy ? 'Creating…' : 'Create project'}</Button
                ><Dialog.Close class={buttonVariants({ variant: 'outline' })}>Cancel</Dialog.Close>
              </div>
            </form></Dialog.Content
          ></Dialog.Root
        >{/if}
    </div>
  </header>
  <nav class="project-scope" aria-label="Project scope">
    <a href={directoryHref(true)} aria-current={publicScope ? 'page' : undefined}>Public</a>
    <a href={directoryHref(false)} aria-current={!publicScope ? 'page' : undefined}>Yours</a>
  </nav>
  {#if !publicScope && !auth.signedIn}
    <p class="muted">
      <a href={accountHref('signin', directoryHref(false))}>Sign in</a> to see your public and private
      projects.
    </p>
  {:else}
    {#if !publicScope}<nav class="project-categories" aria-label="Project categories">
        {#each [['active', 'All'], ['owned', 'Owned'], ['shared', 'Shared'], ['archived', 'Archived']] as [id, label] (id)}<Button
            type="submit"
            variant="ghost"
            aria-current={category === id ? 'page' : undefined}
            onclick={() => chooseCategory(id)}>{label}</Button
          >{/each}
      </nav>{/if}

    <form
      class="toolbar project-toolbar"
      role="search"
      aria-label="Projects"
      onsubmit={(event) => {
        event.preventDefault();
        submitSearch();
      }}
    >
      <div class="project-query">
        <Input
          aria-label="Search"
          bind:ref={searchInput}
          type="search"
          placeholder="Search existing projects"
          bind:value={searchDraft}
        />
        {#if searchDraft || search}
          <Button
            class="project-clear-search"
            variant="ghost"
            size="icon"
            type="button"
            aria-label="Clear search"
            onclick={clearSearch}
          >
            <X size={14} aria-hidden="true" />
          </Button>
        {/if}
      </div>
      <Button type="submit">Search</Button>
      {#if !publicScope}<Field.Label class="project-category-select"
          ><span class="sr-only">Project category</span><NativeSelect
            aria-label="Project category"
            bind:value={category}
            onchange={(event) => chooseCategory(event.currentTarget.value)}
          >
            <option value="active">All</option><option value="owned">Owned</option><option
              value="shared">Shared</option
            ><option value="archived">Archived</option>
          </NativeSelect></Field.Label
        >{/if}
      <Field.Label class="project-sort"
        ><span class="project-sort-label">Sort by</span><NativeSelect
          aria-label="Sort projects"
          bind:value={sort}
          onchange={chooseSort}
        >
          <option value="updated">Recently updated</option><option value="name"
            >Alphabetical ↑ (A–Z)</option
          >
          <option value="name_desc">Alphabetical ↓ (Z–A)</option>
          <option value="relevance" disabled={!search}>Relevance</option>
        </NativeSelect></Field.Label
      >
    </form>
    <div class="project-results-heading" bind:this={resultsHeading} tabindex="-1">
      {#if displayedSearch}<h2>Results for “{displayedSearch}”</h2>{/if}
      <div class="row">
        <span class="muted" aria-live="polite"
          >{items.length
            ? `${displayedPage * pageSize + 1}-${displayedPage * pageSize + items.length}`
            : '0'}{$projects.data?.total !== undefined
            ? ` of ${$projects.data.total} ${displayedSearch ? 'matches' : 'projects'}`
            : ' shown'}</span
        >
      </div>
      <span class="project-refresh" role="status">
        {#if updating}<LoaderCircle size={14} aria-hidden="true" />Updating…{/if}
      </span>
    </div>
    {#if $projects.isPending}<LoadingState>Loading projects…</LoadingState
      >{:else if $projects.isError}<DiscoveryState
        kind="error"
        title="Could not load projects"
        description={explain($projects.error)}
      >
        <Button variant="outline" onclick={() => $projects.refetch()}>Retry</Button>
      </DiscoveryState>{:else if !items.length}<DiscoveryState
        title={search
          ? 'No matching projects'
          : category === 'archived'
            ? 'Archive is empty'
            : 'No projects yet'}
        description={search
          ? publicScope
            ? 'Try different words or clear your search.'
            : 'Try different words or change your filters.'
          : category === 'archived'
            ? 'Archived projects will appear here.'
            : publicScope
              ? 'Public projects will appear here when they are created.'
              : 'Create a project, add a statement, and develop it with your team.'}
      >
        {#if category === 'active' && auth.signedIn}<Button
            type="submit"
            onclick={() => (open = true)}>Create project</Button
          >{/if}
      </DiscoveryState>{:else}<section
        class="project-grid"
        class:updating
        aria-label="Project results"
        aria-busy={updating}
      >
        {#each items as project (project.id)}
          <article class="project-card interactive">
            <div class="project-card-heading">
              <h3 title={project.name}>
                <a href={`/projects/${project.id}`} title={project.name}
                  ><span class="project-name"
                    ><FolderOpen
                      size={16}
                      class="project-folder"
                      aria-hidden="true"
                    />{project.name}</span
                  ></a
                >
              </h3>
            </div>
            <p class="project-description" title={project.description || 'No description yet.'}>
              {project.description || 'No description yet.'}
            </p>
            <footer>
              <div class="project-footer-meta">
                {#if auth.signedIn && project.current_user_role}<span class="project-role"
                    >{project.current_user_role === 'OWNER'
                      ? 'Owner'
                      : project.current_user_role === 'CONTRIBUTOR'
                        ? 'Contributor'
                        : 'Read only'}</span
                  >{/if}

                <div class="visibility-bottom">{@render visibilityLabel(project.visibility)}</div>
                {#if auth.signedIn && project.member_count !== undefined}<span
                    class="project-members"
                    ><Users class="size-4 shrink-0" aria-hidden="true" />{project.member_count}
                    {project.member_count === 1 ? 'member' : 'members'}</span
                  >{/if}
              </div>
              <time
                datetime={project.updated_at}
                title={`Updated ${new Date(project.updated_at).toLocaleString()}`}
                >Updated {new Date(project.updated_at).toLocaleDateString(undefined, {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })}</time
              >
            </footer>
          </article>
        {/each}
      </section>{/if}
    {#if pageIndex > 0 || $projects.data?.nextCursor}
      <nav class="project-pagination" aria-label="Project pages">
        <Button
          variant="outline"
          disabled={pageIndex === 0 || $projects.isFetching}
          onclick={() => changePage(pageIndex - 1)}>Previous</Button
        >
        <span class="muted">Page {displayedPage + 1}</span>
        <Button
          variant="outline"
          disabled={!$projects.data?.nextCursor || $projects.isFetching}
          onclick={() => {
            cursors = [...cursors.slice(0, pageIndex + 1), $projects.data!.nextCursor];
            changePage(pageIndex + 1);
          }}>Next</Button
        >
      </nav>
    {/if}
  {/if}
</main>

{#snippet visibilityLabel(visibility: string)}
  <span
    class="project-visibility"
    class:is-private={visibility === 'PRIVATE'}
    title={visibility === 'PUBLIC'
      ? 'Anyone can read this project'
      : 'Only project members can read this project'}
  >
    {#if visibility === 'PUBLIC'}<Globe size={14} aria-hidden="true" />Public
    {:else}<LockKeyhole size={14} aria-hidden="true" />Private{/if}
  </span>
{/snippet}

<style>
  .project-pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    margin-top: 20px;
  }
  .project-scope {
    display: flex;
    width: fit-content;
    gap: 4px;
    padding: 3px;
    margin: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--muted);
  }
  .project-scope a {
    padding: 6px 14px;
    border-radius: var(--radius);
    color: var(--muted-foreground);
    font-size: 14px;
    font-weight: 400;
    text-decoration: none;
  }
  .project-scope a[aria-current='page'] {
    background: var(--panel);
    color: var(--foreground);
    box-shadow: 0 1px 3px var(--polycolab-shadow);
  }
  .project-scope a:hover {
    color: var(--foreground);
  }

  .page.project-page {
    gap: 16px;
    padding-top: 24px;
  }
  .project-title,
  .project-results-heading {
    scroll-margin-top: 88px;
    justify-content: space-between;
  }
  .project-toolbar {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    gap: 8px;
    margin: 0;
    padding: 0;
    align-items: center;
  }
  .project-toolbar :global(.project-query),
  .project-toolbar :global(.project-sort) {
    min-width: 0;
    margin: 0;
    gap: 0;
  }
  .project-toolbar :global(.project-sort) {
    flex-direction: row;
    align-items: center;
    gap: 8px;
    grid-column: 3;
    grid-row: 1;
  }
  .project-query {
    position: relative;
  }
  .project-query :global(input) {
    padding-right: 36px;
  }
  .project-query :global(input::-webkit-search-cancel-button) {
    display: none;
  }
  .project-query :global(.project-clear-search) {
    position: absolute;
    right: 4px;
    top: 50%;
    transform: translateY(-50%);
    width: 28px;
    height: 28px;
  }
  .project-refresh {
    min-width: 82px;
    min-height: 20px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .project-refresh :global(svg) {
    animation: project-spin 1s linear infinite;
  }
  .project-grid.updating {
    opacity: 0.65;
  }
  @keyframes project-spin {
    to {
      transform: rotate(360deg);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .project-refresh :global(svg) {
      animation: none;
    }
  }
  .project-sort-label {
    white-space: nowrap;
    color: var(--muted-foreground);
  }
  .project-toolbar :global(.project-sort select) {
    width: 180px;
  }
  .project-toolbar :global(.project-category-select) {
    grid-column: 1 / -1;
    grid-row: 2;
  }
  .project-results-heading {
    scroll-margin-top: 88px;
    display: flex;
    align-items: baseline;
    gap: 16px;
    flex-wrap: wrap;
  }
  .project-results-heading h2 {
    margin: 0;
    font-size: 20px;
  }
  .project-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
  .project-card {
    height: 160px;
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
  }
  .project-card.interactive:hover,
  .project-card:focus-within {
    border-color: var(--line-strong);
    background: color-mix(in srgb, var(--muted) 40%, var(--panel));
  }
  .project-card footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    font-size: 11px;
    line-height: 16px;
    color: var(--muted-foreground);
  }
  .project-card-heading {
    min-height: 44.8px;
    flex-shrink: 0;
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }
  .project-card-heading h3 {
    flex: 1;
    min-width: 0;
  }
  .project-footer-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .project-name {
    word-break: break-all;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .project-card h3 a {
    min-width: 0;
  }
  .project-card footer {
    flex-wrap: wrap;
    gap: 8px;
  }
  .visibility-bottom {
    display: flex;
    align-items: center;
  }
  .project-card footer time {
    display: inline-flex;
    align-items: center;
    min-height: 22px;
  }
  .project-members,
  .project-visibility {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 22px;
    line-height: 16px;
  }
  .project-visibility {
    --visibility-color: var(--research-accent);
    color: color-mix(in srgb, var(--visibility-color) 70%, var(--muted-foreground));
    white-space: nowrap;
    font-weight: 400;
    line-height: 16px;
  }
  .project-visibility :global(svg) {
    color: var(--visibility-color);
  }
  .project-visibility.is-private {
    --visibility-color: var(--info);
  }
  .project-role {
    color: var(--foreground);
    background: var(--muted);
    font-weight: 500;
    display: inline-flex;
    align-items: center;
    min-height: 22px;
    line-height: 16px;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 6px;
  }
  .project-card h3 {
    margin: 0;
    font-size: 16px;
    line-height: 1.4;
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  :global(.project-folder) {
    display: inline;
    vertical-align: -2px;
    margin-right: 8px;
    color: var(--muted-foreground);
  }
  .project-card h3 a {
    color: var(--foreground);
    text-decoration: none;
  }
  .project-card h3 a::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: var(--radius);
  }
  .project-card h3 a:focus-visible {
    outline: none;
  }
  .project-card:has(a:focus-visible) {
    outline: 2px solid var(--brand);
    outline-offset: 2px;
  }
  .project-description {
    height: 36px;
    flex-shrink: 0;
    margin: 0;
    font-size: 13px;
    line-height: 18px;
    color: var(--muted-foreground);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .project-card footer {
    margin-top: auto;
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }
  @media (max-width: 1000px) {
    .project-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  @media (max-width: 700px) {
    .project-toolbar {
      grid-template-columns: minmax(0, 1fr) auto minmax(120px, 140px);
      gap: 8px;
    }
    .project-sort-label {
      display: none;
    }
    .project-toolbar :global(.project-sort select) {
      width: 100%;
    }
    .project-grid {
      grid-template-columns: minmax(0, 1fr);
      gap: 10px;
    }
    .project-card {
      height: 180px;
      padding: 14px;
      gap: 6px;
    }
  }
</style>
