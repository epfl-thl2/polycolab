<script lang="ts">
  import {
    ChevronDown,
    ChevronRight,
    FileCode2,
    FileText,
    Folder,
    FolderOpen,
    Search,
  } from '@lucide/svelte';
  import { tick, untrack } from 'svelte';
  import {
    fileTree,
    fileDecorations,
    createExplorerView,
    type ExplorerNode,
    type ExplorerViewState,
    type FileChange,
  } from '../lib/file-explorer';
  let {
    paths,
    selected = '',
    hasHiddenFiles = false,
    disabled = false,
    onopen,
    onreveal,
    viewState = $bindable(),
    changes = [],
  }: {
    paths: string[];
    selected?: string;
    hasHiddenFiles?: boolean;
    disabled?: boolean;
    onopen: (path: string, mode?: 'preview' | 'permanent') => void;
    onreveal?: () => void;
    viewState?: ExplorerViewState;
    changes?: FileChange[];
  } = $props();
  const localView = $state(createExplorerView());
  const currentView = $derived(viewState ?? localView);
  let treeElement: HTMLElement;
  const filteredPaths = $derived(
    paths.filter((path) =>
      path.toLocaleLowerCase().includes(currentView.filter.toLocaleLowerCase()),
    ),
  );
  const tree = $derived(fileTree(filteredPaths));
  const decorations = $derived(fileDecorations(paths, changes));
  const selectedHidden = $derived(Boolean(selected && !filteredPaths.includes(selected)));
  function toggle(path: string) {
    currentView.collapsed = currentView.collapsed.includes(path)
      ? currentView.collapsed.filter((value) => value !== path)
      : [...currentView.collapsed, path];
  }
  async function reveal() {
    const name = selected;
    const view = currentView;
    if (!name) return;
    const parts = name.split('/');
    const ancestors = parts.slice(0, -1).map((_, index) => parts.slice(0, index + 1).join('/'));
    view.collapsed = view.collapsed.filter((path) => !ancestors.includes(path));
    await tick();
    if (currentView !== view || selected !== name) return;
    const row = treeElement?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!row) return;
    const bounds = row.getBoundingClientRect();
    const viewport = treeElement.getBoundingClientRect();
    if (bounds.top < viewport.top) treeElement.scrollTop += bounds.top - viewport.top;
    else if (bounds.bottom > viewport.bottom)
      treeElement.scrollTop += bounds.bottom - viewport.bottom;
    view.scrollTop = treeElement.scrollTop;
  }
  $effect(() => {
    const view = currentView;
    untrack(() => {
      void tick().then(() => {
        if (currentView === view && treeElement) treeElement.scrollTop = view.scrollTop;
      });
    });
  });
  $effect(() => {
    const name = selected;
    const view = currentView;
    if (!name) return;
    untrack(() => {
      if (view.lastSelected === name) return;
      view.lastSelected = name;
      if (!selectedHidden) void reveal();
    });
  });
  async function revealExplicitly() {
    currentView.filter = '';
    onreveal?.();
    await tick();
    await reveal();
  }
</script>

<div class="explorer-filter">
  <Search size={14} aria-hidden="true" />
  <input aria-label="Find a file" placeholder="Find a file…" bind:value={currentView.filter} />
</div>
{#if selectedHidden}<button class="reveal-file" onclick={revealExplicitly}
    >Reveal active file</button
  >{/if}
<nav
  bind:this={treeElement}
  aria-label="File tree"
  class="file-tree"
  onscroll={() => {
    currentView.scrollTop = treeElement.scrollTop;
  }}
>
  {@render nodes(tree, 0)}
  {#if !paths.length}<p class="empty">
      {hasHiddenFiles
        ? 'Files are hidden by your view options.'
        : 'No files yet. Create a file or upload your research.'}
    </p>
  {:else if !tree.length}<p class="empty">No matching files.</p>{/if}
</nav>

{#snippet nodes(items: ExplorerNode[], depth: number)}
  {#each items as item (item.path)}
    {@const status = decorations.get(item.path)}
    {#if item.directory}
      {@const expanded = Boolean(currentView.filter) || !currentView.collapsed.includes(item.path)}
      <button
        class="tree-row folder"
        style={`--depth:${depth}`}
        aria-expanded={expanded}
        onclick={() => toggle(item.path)}
        title={item.path}
      >
        {#if expanded}<ChevronDown size={13} aria-hidden="true" /><FolderOpen
            size={14}
            aria-hidden="true"
          />
        {:else}<ChevronRight size={13} aria-hidden="true" /><Folder
            size={14}
            aria-hidden="true"
          />{/if}
        <span>{item.name}</span>{@render badge(status)}
      </button>
      {#if expanded}{@render nodes(item.children, depth + 1)}{/if}
    {:else}
      <button
        class="tree-row file"
        style={`--depth:${depth}`}
        aria-current={selected === item.path ? 'page' : undefined}
        {disabled}
        onclick={(event) => onopen(item.path, event.detail >= 2 ? 'permanent' : 'preview')}
        ondblclick={() => onopen(item.path, 'permanent')}
        onkeydown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            onopen(item.path, 'permanent');
          }
        }}
        title={item.path}
      >
        {#if /\.(lean|py|json|ts|js|toml|yaml|yml)$/.test(item.name)}<FileCode2
            size={14}
            aria-hidden="true"
          />{:else}<FileText size={14} aria-hidden="true" />{/if}
        <span>{item.name}</span>{@render badge(status)}
      </button>
    {/if}
  {/each}
{/snippet}

{#snippet badge(status: FileChange['status'] | undefined)}
  {#if status}<small
      class="git-status"
      data-status={status}
      aria-label={`Saved changes: ${status}`}
      title={`Saved changes: ${status}`}
    >
      {{ added: 'A', modified: 'M', deleted: 'D' }[status]}
    </small>{/if}
{/snippet}

<style>
  .explorer-filter {
    display: flex;
    align-items: center;
    gap: 4px;
    margin: 4px 8px 6px;
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted-foreground);
    background: var(--background);
  }
  input {
    width: 100%;
    min-width: 0;
    background: transparent;
    border: 0;
    font: inherit;
    font-size: 11px;
    line-height: 16px;
    color: var(--foreground);
    outline: none;
  }
  .explorer-filter:focus-within {
    outline: 2px solid var(--ring);
    outline-offset: 1px;
  }
  .file-tree {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding-bottom: 8px;
  }
  .tree-row {
    display: flex;
    width: 100%;
    min-height: 24px;
    align-items: center;
    gap: 4px;
    padding: 2px 8px 2px calc(8px + var(--depth) * 12px);
    text-align: left;
    font-size: 11px;
    line-height: 16px;
    border-left: 2px solid transparent;
  }
  .file {
    padding-left: calc(25px + var(--depth) * 12px);
  }
  .git-status {
    margin-left: auto;
    flex-shrink: 0;
    font-size: 10px;
    font-weight: 600;
  }
  .git-status[data-status='added'] {
    color: var(--success);
  }
  .git-status[data-status='modified'] {
    color: var(--warning);
  }
  .git-status[data-status='deleted'] {
    color: var(--destructive);
  }
  .reveal-file {
    padding: 4px 8px;
    color: var(--brand-strong);
    text-align: left;
    font-size: 11px;
  }
  .tree-row span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tree-row :global(svg) {
    flex-shrink: 0;
    color: var(--muted-foreground);
  }
  .tree-row:hover {
    background: var(--muted);
  }
  .tree-row[aria-current] {
    border-left-color: var(--sidebar-accent);
    background: var(--sidebar-accent);
    color: var(--sidebar-accent-foreground);
    font-weight: 550;
  }
  .tree-row[aria-current] :global(svg) {
    color: var(--sidebar-accent-foreground);
  }
  .tree-row:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
  }
  .empty {
    color: var(--muted-foreground);
    font-size: 11px;
    padding: 6px 8px;
    line-height: 1.6;
  }
</style>
