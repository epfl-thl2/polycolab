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
  import { fileTree, type ExplorerNode } from '../lib/file-explorer';
  let {
    paths,
    selected = '',
    disabled = false,
    onopen,
  }: {
    paths: string[];
    selected?: string;
    disabled?: boolean;
    onopen: (path: string) => void;
  } = $props();
  let filter = $state('');
  let collapsed = $state<string[]>([]);
  const tree = $derived(
    fileTree(paths.filter((path) => path.toLocaleLowerCase().includes(filter.toLocaleLowerCase()))),
  );
  function toggle(path: string) {
    collapsed = collapsed.includes(path)
      ? collapsed.filter((value) => value !== path)
      : [...collapsed, path];
  }
</script>

<div class="explorer-filter">
  <Search size={14} aria-hidden="true" />
  <input aria-label="Find a file" placeholder="Find a file…" bind:value={filter} />
</div>
<nav aria-label="File tree" class="file-tree">
  {@render nodes(tree, 0)}
  {#if !paths.length}<p class="empty">No files yet. Create a file or upload your research.</p>
  {:else if !tree.length}<p class="empty">No matching files.</p>{/if}
</nav>

{#snippet nodes(items: ExplorerNode[], depth: number)}
  {#each items as item (item.path)}
    {#if item.directory}
      {@const expanded = Boolean(filter) || !collapsed.includes(item.path)}
      <button
        class="tree-row folder"
        style={`--depth:${depth}`}
        aria-expanded={expanded}
        onclick={() => toggle(item.path)}
        title={item.path}
      >
        {#if expanded}<ChevronDown size={13} aria-hidden="true" /><FolderOpen
            size={15}
            aria-hidden="true"
          />
        {:else}<ChevronRight size={13} aria-hidden="true" /><Folder
            size={15}
            aria-hidden="true"
          />{/if}
        <span>{item.name}</span>
      </button>
      {#if expanded}{@render nodes(item.children, depth + 1)}{/if}
    {:else}
      <button
        class="tree-row file"
        style={`--depth:${depth}`}
        aria-current={selected === item.path ? 'page' : undefined}
        {disabled}
        onclick={() => onopen(item.path)}
        title={item.path}
      >
        {#if /\.(lean|py|json|ts|js|toml|yaml|yml)$/.test(item.name)}<FileCode2
            size={15}
            aria-hidden="true"
          />{:else}<FileText size={15} aria-hidden="true" />{/if}
        <span>{item.name}</span>
      </button>
    {/if}
  {/each}
{/snippet}

<style>
  .explorer-filter {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0.65rem 0.6rem;
    padding: 0.35rem 0.45rem;
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
    font-size: 0.75rem;
    color: var(--foreground);
    outline: none;
  }
  .explorer-filter:focus-within {
    outline: 2px solid var(--ring);
    outline-offset: 1px;
  }
  .file-tree {
    padding-bottom: 1rem;
  }
  .tree-row {
    display: flex;
    width: 100%;
    min-height: 30px;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0.7rem 0.3rem calc(0.65rem + var(--depth) * 0.85rem);
    text-align: left;
    font-size: 0.78rem;
    border-left: 2px solid transparent;
  }
  .file {
    padding-left: calc(1.55rem + var(--depth) * 0.85rem);
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
    border-left-color: var(--primary);
    background: var(--accent-soft);
    color: var(--primary);
    font-weight: 550;
  }
  .tree-row[aria-current] :global(svg) {
    color: var(--primary);
  }
  .tree-row:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
  }
  .empty {
    color: var(--muted-foreground);
    font-size: 0.78rem;
    padding: 0.6rem 1rem;
    line-height: 1.6;
  }
</style>
