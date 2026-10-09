<script lang="ts">
  import type { Page, Project, PublicProject } from '../lib/research-api';
  type WorkspaceListingItem = PublicProject &
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
  import { workspace, explain } from '../svelte-lib/context';
  let { publicScope = false }: { publicScope?: boolean } = $props();
  type WorkspacePage = Page<WorkspaceListingItem> & { pageIndex: number; search: string };
  const basePath = '/workspaces';
  const { api, query, auth } = workspace();
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
    toStore<CreateQueryOptions<WorkspacePage>>(() => ({
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
      queryFn: async (): Promise<WorkspacePage> => {
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
      await goto(`/workspaces/${project.id}`);
    } catch (reason) {
      error = explain(reason);
    } finally {
      busy = false;
    }
  }
</script>

<main id="main" class="page discovery-page workspace-page" tabindex="-1">
  <header class="discovery-heading">
    <div class="discovery-title workspace-title">
      <h1>Workspaces</h1>
      {#if auth.signedIn}
        <Dialog.Root bind:open
          ><Dialog.Trigger class={buttonVariants()}>New workspace</Dialog.Trigger><Dialog.Content
            class="sm:max-w-lg"
            ><Dialog.Header class="pr-8"
              ><Dialog.Title class="leading-snug">What are you investigating?</Dialog.Title
              ><Dialog.Description
                >Choose who can view this workspace. Members can contribute according to their role.</Dialog.Description
              ></Dialog.Header
            >
            <form onsubmit={create}>
              <Field.Label
                >Workspace name<Input required maxlength={200} bind:value={name} /></Field.Label
              ><Field.Label>Description<Textarea bind:value={description}></Textarea></Field.Label>
              <Field.Label
                >Visibility<NativeSelect bind:value={visibility}>
                  <option value="PUBLIC">Public</option>
                  <option value="PRIVATE">Private</option>
                </NativeSelect></Field.Label
              >
              <p>
                {visibility === 'PUBLIC'
                  ? 'Anyone can view this workspace and its research.'
                  : 'Only members can view this workspace and its research.'}
              </p>
              {#if error}<Alert.Root variant="destructive" role="alert">
                  {error}
                </Alert.Root>{/if}
              <div class="row">
                <Button type="submit" disabled={busy || !name.trim()}
                  >{busy ? 'Creating…' : 'Create workspace'}</Button
                ><Dialog.Close class={buttonVariants({ variant: 'outline' })}>Cancel</Dialog.Close>
              </div>
            </form></Dialog.Content
          ></Dialog.Root
        >{/if}
    </div>
  </header>
  <nav class="workspace-scope" aria-label="Workspace scope">
    <a href={directoryHref(true)} aria-current={publicScope ? 'page' : undefined}>Public</a>
    <a href={directoryHref(false)} aria-current={!publicScope ? 'page' : undefined}>Yours</a>
  </nav>
  {#if !publicScope && !auth.signedIn}
    <p class="muted">
      <a href={accountHref('signin', directoryHref(false))}>Sign in</a> to see your public and private
      workspaces.
    </p>
  {:else}
    {#if !publicScope}<nav class="workspace-categories" aria-label="Workspace categories">
        {#each [['active', 'All'], ['owned', 'Owned'], ['shared', 'Shared'], ['archived', 'Archived']] as [id, label] (id)}<Button
            type="submit"
            variant="ghost"
            aria-current={category === id ? 'page' : undefined}
            onclick={() => chooseCategory(id)}>{label}</Button
          >{/each}
      </nav>{/if}

    <form
      class="toolbar workspace-toolbar"
      role="search"
      aria-label="Workspaces"
      onsubmit={(event) => {
        event.preventDefault();
        submitSearch();
      }}
    >
      <div class="workspace-query">
        <Input
          aria-label="Search"
          bind:ref={searchInput}
          type="search"
          placeholder="Search existing workspaces"
          bind:value={searchDraft}
        />
        {#if searchDraft || search}
          <Button
            class="workspace-clear-search"
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
      {#if !publicScope}<Field.Label class="workspace-category-select"
          ><span class="sr-only">Workspace category</span><NativeSelect
            aria-label="Workspace category"
            bind:value={category}
            onchange={(event) => chooseCategory(event.currentTarget.value)}
          >
            <option value="active">All</option><option value="owned">Owned</option><option
              value="shared">Shared</option
            ><option value="archived">Archived</option>
          </NativeSelect></Field.Label
        >{/if}
      <Field.Label class="workspace-sort"
        ><span class="workspace-sort-label">Sort by</span><NativeSelect
          aria-label="Sort workspaces"
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
    <div class="workspace-results-heading" bind:this={resultsHeading} tabindex="-1">
      {#if displayedSearch}<h2>Results for “{displayedSearch}”</h2>{/if}
      <div class="row">
        <span class="muted" aria-live="polite"
          >{items.length
            ? `${displayedPage * pageSize + 1}-${displayedPage * pageSize + items.length}`
            : '0'}{$projects.data?.total !== undefined
            ? ` of ${$projects.data.total} ${displayedSearch ? 'matches' : 'workspaces'}`
            : ' shown'}</span
        >
      </div>
      <span class="workspace-refresh" role="status">
        {#if updating}<LoaderCircle size={14} aria-hidden="true" />Updating…{/if}
      </span>
    </div>
    {#if $projects.isPending}<LoadingState>Loading workspaces…</LoadingState
      >{:else if $projects.isError}<DiscoveryState
        kind="error"
        title="Could not load workspaces"
        description={explain($projects.error)}
      >
        <Button variant="outline" onclick={() => $projects.refetch()}>Retry</Button>
      </DiscoveryState>{:else if !items.length}<DiscoveryState
        title={search
          ? 'No matching workspaces'
          : category === 'archived'
            ? 'Archive is empty'
            : 'No workspaces yet'}
        description={search
          ? publicScope
            ? 'Try different words or clear your search.'
            : 'Try different words or change your filters.'
          : category === 'archived'
            ? 'Archived workspaces will appear here.'
            : publicScope
              ? 'Public workspaces will appear here when they are created.'
              : 'Create a workspace, add a statement, and develop it with your team.'}
      >
        {#if category === 'active' && auth.signedIn}<Button
            type="submit"
            onclick={() => (open = true)}>Create workspace</Button
          >{/if}
      </DiscoveryState>{:else}<section
        class="workspace-grid"
        class:updating
        aria-label="Workspace results"
        aria-busy={updating}
      >
        {#each items as project (project.id)}
          <article class="workspace-card interactive">
            <div class="workspace-card-heading">
              <h3 title={project.name}>
                <a href={`/workspaces/${project.id}`} title={project.name}
                  ><span class="workspace-name"
                    ><FolderOpen
                      size={16}
                      class="workspace-folder"
                      aria-hidden="true"
                    />{project.name}</span
                  ></a
                >
              </h3>
            </div>
            <p class="workspace-description" title={project.description || 'No description yet.'}>
              {project.description || 'No description yet.'}
            </p>
            <footer>
              <div class="workspace-footer-meta">
                {#if auth.signedIn && project.current_user_role}<span class="workspace-role"
                    >{project.current_user_role === 'OWNER'
                      ? 'Owner'
                      : project.current_user_role === 'CONTRIBUTOR'
                        ? 'Contributor'
                        : 'Read only'}</span
                  >{/if}

                <div class="visibility-bottom">{@render visibilityLabel(project.visibility)}</div>
                {#if auth.signedIn && project.member_count !== undefined}<span
                    class="workspace-members"
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
      <nav class="workspace-pagination" aria-label="Workspace pages">
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
    class="workspace-visibility"
    class:is-private={visibility === 'PRIVATE'}
    title={visibility === 'PUBLIC'
      ? 'Anyone can read this workspace'
      : 'Only workspace members can read this workspace'}
  >
    {#if visibility === 'PUBLIC'}<Globe size={14} aria-hidden="true" />Public
    {:else}<LockKeyhole size={14} aria-hidden="true" />Private{/if}
  </span>
{/snippet}

<style>
  .workspace-pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    margin-top: 20px;
  }
  .workspace-scope {
    display: flex;
    width: fit-content;
    gap: 4px;
    padding: 3px;
    margin: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    background: var(--muted);
  }
  .workspace-scope a {
    padding: 6px 14px;
    border-radius: var(--radius);
    color: var(--muted-foreground);
    font-size: 14px;
    font-weight: 400;
    text-decoration: none;
  }
  .workspace-scope a[aria-current='page'] {
    background: var(--panel);
    color: var(--foreground);
    box-shadow: 0 1px 3px var(--polycolab-shadow);
  }
  .workspace-scope a:hover {
    color: var(--foreground);
  }

  .page.workspace-page {
    gap: 16px;
    padding-top: 24px;
  }
  .workspace-title,
  .workspace-results-heading {
    scroll-margin-top: 88px;
    justify-content: space-between;
  }
  .workspace-toolbar {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    gap: 8px;
    margin: 0;
    padding: 0;
    align-items: center;
  }
  .workspace-toolbar :global(.workspace-query),
  .workspace-toolbar :global(.workspace-sort) {
    min-width: 0;
    margin: 0;
    gap: 0;
  }
  .workspace-toolbar :global(.workspace-sort) {
    flex-direction: row;
    align-items: center;
    gap: 8px;
    grid-column: 3;
    grid-row: 1;
  }
  .workspace-query {
    position: relative;
  }
  .workspace-query :global(input) {
    padding-right: 36px;
  }
  .workspace-query :global(input::-webkit-search-cancel-button) {
    display: none;
  }
  .workspace-query :global(.workspace-clear-search) {
    position: absolute;
    right: 4px;
    top: 50%;
    transform: translateY(-50%);
    width: 28px;
    height: 28px;
  }
  .workspace-refresh {
    min-width: 82px;
    min-height: 20px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .workspace-refresh :global(svg) {
    animation: workspace-spin 1s linear infinite;
  }
  .workspace-grid.updating {
    opacity: 0.65;
  }
  @keyframes workspace-spin {
    to {
      transform: rotate(360deg);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .workspace-refresh :global(svg) {
      animation: none;
    }
  }
  .workspace-sort-label {
    white-space: nowrap;
    color: var(--muted-foreground);
  }
  .workspace-toolbar :global(.workspace-sort select) {
    width: 180px;
  }
  .workspace-toolbar :global(.workspace-category-select) {
    grid-column: 1 / -1;
    grid-row: 2;
  }
  .workspace-results-heading {
    scroll-margin-top: 88px;
    display: flex;
    align-items: baseline;
    gap: 16px;
    flex-wrap: wrap;
  }
  .workspace-results-heading h2 {
    margin: 0;
    font-size: 20px;
  }
  .workspace-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
  .workspace-card {
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
  .workspace-card.interactive:hover,
  .workspace-card:focus-within {
    border-color: var(--line-strong);
    background: color-mix(in srgb, var(--muted) 40%, var(--panel));
  }
  .workspace-card footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    font-size: 11px;
    line-height: 16px;
    color: var(--muted-foreground);
  }
  .workspace-card-heading {
    min-height: 44.8px;
    flex-shrink: 0;
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }
  .workspace-card-heading h3 {
    flex: 1;
    min-width: 0;
  }
  .workspace-footer-meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .workspace-name {
    word-break: break-all;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .workspace-card h3 a {
    min-width: 0;
  }
  .workspace-card footer {
    flex-wrap: wrap;
    gap: 8px;
  }
  .visibility-bottom {
    display: flex;
    align-items: center;
  }
  .workspace-card footer time {
    display: inline-flex;
    align-items: center;
    min-height: 22px;
  }
  .workspace-members,
  .workspace-visibility {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    min-height: 22px;
    line-height: 16px;
  }
  .workspace-visibility {
    --visibility-color: var(--research-accent);
    color: color-mix(in srgb, var(--visibility-color) 70%, var(--muted-foreground));
    white-space: nowrap;
    font-weight: 400;
    line-height: 16px;
  }
  .workspace-visibility :global(svg) {
    color: var(--visibility-color);
  }
  .workspace-visibility.is-private {
    --visibility-color: var(--info);
  }
  .workspace-role {
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
  .workspace-card h3 {
    margin: 0;
    font-size: 16px;
    line-height: 1.4;
    font-weight: 600;
    overflow-wrap: anywhere;
  }
  :global(.workspace-folder) {
    display: inline;
    vertical-align: -2px;
    margin-right: 8px;
    color: var(--muted-foreground);
  }
  .workspace-card h3 a {
    color: var(--foreground);
    text-decoration: none;
  }
  .workspace-card h3 a::after {
    content: '';
    position: absolute;
    inset: 0;
    border-radius: var(--radius);
  }
  .workspace-card h3 a:focus-visible {
    outline: none;
  }
  .workspace-card:has(a:focus-visible) {
    outline: 2px solid var(--brand);
    outline-offset: 2px;
  }
  .workspace-description {
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
  .workspace-card footer {
    margin-top: auto;
    padding-top: 10px;
    border-top: 1px solid var(--border);
  }
  @media (max-width: 1000px) {
    .workspace-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  @media (max-width: 700px) {
    .workspace-toolbar {
      grid-template-columns: minmax(0, 1fr) auto minmax(120px, 140px);
      gap: 8px;
    }
    .workspace-sort-label {
      display: none;
    }
    .workspace-toolbar :global(.workspace-sort select) {
      width: 100%;
    }
    .workspace-grid {
      grid-template-columns: minmax(0, 1fr);
      gap: 10px;
    }
    .workspace-card {
      height: 180px;
      padding: 14px;
      gap: 6px;
    }
  }
</style>
