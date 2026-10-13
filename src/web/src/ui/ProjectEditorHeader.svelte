<script lang="ts">
  import {
    Code2,
    Eye,
    GitCompareArrows,
    Save,
    Ellipsis,
    Copy,
    Pencil,
    Download,
    Trash2,
    WrapText,
    Check,
  } from '@lucide/svelte';
  import * as Tooltip from '../lib/components/ui/tooltip';
  import * as DropdownMenu from '../lib/components/ui/dropdown-menu';
  let {
    path = $bindable(),
    mode = $bindable('source'),
    renaming = $bindable(false),
    wordWrap = $bindable(true),
    enhanced = $bindable(true),
    binary,
    writable,
    busy,
    dirty,
    saved,
    onsave,
    onrename,
    ondownload,
    ondelete,
    onerror,
  }: {
    path: string;
    mode?: 'source' | 'preview' | 'changes';
    renaming?: boolean;
    wordWrap?: boolean;
    enhanced?: boolean;
    binary: boolean;
    writable: boolean;
    busy: boolean;
    dirty: boolean;
    saved: boolean;
    onsave: () => void;
    onrename: () => void;
    ondownload: () => void;
    ondelete: () => void;
    onerror: (message: string) => void;
  } = $props();
  const prefix = $derived(path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : '');
  const filename = $derived(path.slice(path.lastIndexOf('/') + 1) || 'Untitled');
  const markdown = $derived(/\.(md|markdown)$/i.test(path));
  const modes = $derived([
    {
      value: 'source' as const,
      label: markdown ? 'Source' : 'Edit',
      hint: markdown ? 'Markdown source' : 'Edit file',
      icon: Code2,
    },
    ...(markdown
      ? [{ value: 'preview' as const, label: 'Preview', hint: 'Preview Markdown', icon: Eye }]
      : []),
    {
      value: 'changes' as const,
      label: 'Changes',
      hint: 'Changes from HEAD, including unsaved edits',
      icon: GitCompareArrows,
    },
  ]);
  let copied = $state(false);
  let copiedPath = $state('');
  let renameRequested = false;
  async function copyPath() {
    const name = path;
    try {
      await navigator.clipboard.writeText(name);
      copiedPath = name;
      copied = true;
    } catch {
      onerror('Could not copy the file path.');
    }
  }
  $effect(() => {
    if (!copied) return;
    const timer = setTimeout(() => (copied = false), 1600);
    return () => clearTimeout(timer);
  });
  function renameInput(node: HTMLInputElement) {
    const before = path;
    node.focus();
    node.setSelectionRange(prefix.length, path.length);
    function key(event: KeyboardEvent) {
      if (event.isComposing) return;
      if (event.key === 'Enter') {
        event.preventDefault();
        if (path.trim()) renaming = false;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        path = before;
        renaming = false;
      }
    }
    node.addEventListener('keydown', key);
    return { destroy: () => node.removeEventListener('keydown', key) };
  }
</script>

<Tooltip.Provider delayDuration={300}>
  <header class="editor-header" aria-label="File editor controls">
    <div class="path-area">
      {#if renaming}
        <input
          use:renameInput
          aria-label="File path"
          placeholder="e.g. proofs/Main.lean"
          bind:value={path}
          disabled={!writable || busy || binary}
          spellcheck="false"
          onblur={() => {
            if (path.trim()) renaming = false;
          }}
        />
      {:else}
        <Tooltip.Root>
          <Tooltip.Trigger>
            {#snippet child({ props })}
              <button
                {...props}
                class="file-path"
                aria-label={`Copy path: ${path || 'Untitled'}`}
                disabled={!path}
                onclick={copyPath}
              >
                <span class="path-prefix">{prefix}</span><span class="filename">{filename}</span>
              </button>
            {/snippet}
          </Tooltip.Trigger>
          <Tooltip.Content class="text-[11px] px-2 py-1"
            >{path || 'Untitled'} · Click to copy path</Tooltip.Content
          >
        </Tooltip.Root>
      {/if}
      {#if copied && path === copiedPath}<span class="copied" role="status"
          ><Check size={12} />Copied</span
        >{/if}
    </div>
    {#if !binary}
      <div class="view-toggle" role="group" aria-label="Editor view">
        {#each modes as item (item.value)}
          <Tooltip.Root>
            <Tooltip.Trigger>
              {#snippet child({ props })}
                <button
                  {...props}
                  class="view-button"
                  aria-label={item.label}
                  aria-pressed={mode === item.value}
                  onclick={() => (mode = item.value)}
                  ><item.icon size={14} aria-hidden="true" /></button
                >
              {/snippet}
            </Tooltip.Trigger>
            <Tooltip.Content class="text-[11px] px-2 py-1">{item.hint}</Tooltip.Content>
          </Tooltip.Root>
        {/each}
      </div>
    {/if}
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <button
            {...props}
            class="icon-button"
            class:unsaved={dirty}
            aria-label="Save"
            disabled={!writable || busy || binary || !path || !dirty}
            onclick={onsave}><Save size={14} aria-hidden="true" /></button
          >
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content class="text-[11px] px-2 py-1">Save · ⌘/Ctrl+S</Tooltip.Content>
    </Tooltip.Root>
    <DropdownMenu.Root>
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <DropdownMenu.Trigger {...props} class="editor-more" aria-label="File actions"
              ><Ellipsis size={14} aria-hidden="true" /></DropdownMenu.Trigger
            >
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content class="text-[11px] px-2 py-1">More actions</Tooltip.Content>
      </Tooltip.Root>
      <DropdownMenu.Content
        align="end"
        class="editor-menu w-48"
        onCloseAutoFocus={(event) => {
          // Keep focus in the inline rename input when the menu closes.
          if (renameRequested) {
            event.preventDefault();
            renameRequested = false;
          }
        }}
      >
        {#if !binary}
          <DropdownMenu.CheckboxItem class="text-[11px]" bind:checked={wordWrap}
            ><WrapText size={14} />Word wrap</DropdownMenu.CheckboxItem
          >
          <DropdownMenu.Item
            class="text-[11px]"
            disabled={busy}
            onSelect={() => {
              enhanced = !enhanced;
              mode = 'source';
            }}
          >
            <Code2 size={14} />{enhanced ? 'Use text editor' : 'Use code editor'}
          </DropdownMenu.Item>
          <DropdownMenu.Separator />
        {/if}
        <DropdownMenu.Item class="text-[11px]" disabled={!path} onSelect={copyPath}
          ><Copy size={14} />Copy path</DropdownMenu.Item
        >
        <DropdownMenu.Item
          class="text-[11px]"
          disabled={!writable || busy || binary}
          onSelect={() => {
            renameRequested = true;
            onrename();
          }}><Pencil size={14} />Rename file</DropdownMenu.Item
        >
        <DropdownMenu.Item class="text-[11px]" disabled={busy || !saved} onSelect={ondownload}
          ><Download size={14} />Download</DropdownMenu.Item
        >
        <DropdownMenu.Separator />
        <DropdownMenu.Item
          class="text-[11px]"
          variant="destructive"
          disabled={!writable || busy || !saved}
          onSelect={ondelete}><Trash2 size={14} />Delete file</DropdownMenu.Item
        >
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  </header>
</Tooltip.Provider>

<style>
  .editor-header {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    min-height: 32px;
    flex-shrink: 0;
    padding: 0 8px 0 12px;
    border-bottom: 1px solid var(--border);
    background: var(--background);
  }
  .path-area {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .file-path {
    display: flex;
    min-width: 0;
    max-width: 100%;
    align-items: center;
    font: 11px/16px var(--font-mono, monospace);
    text-align: left;
    border-radius: 3px;
  }
  .path-prefix {
    color: var(--muted-foreground);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 0 1 auto;
  }
  .filename {
    color: var(--foreground);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 0 0 auto;
    max-width: 100%;
  }
  .file-path:hover .filename {
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .copied {
    display: flex;
    align-items: center;
    gap: 3px;
    flex-shrink: 0;
    font-size: 10px;
    color: var(--muted-foreground);
  }
  input {
    height: 24px;
    width: 100%;
    min-width: 0;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0 6px;
    background: var(--muted);
    color: var(--foreground);
    font: 11px var(--font-mono, monospace);
  }
  .view-toggle {
    display: flex;
    height: 23px;
    border: 1px solid var(--border);
    border-radius: 5px;
    overflow: hidden;
    flex-shrink: 0;
  }
  .view-button,
  .icon-button,
  :global(.editor-more) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 23px;
    width: 26px;
    padding: 0;
    border-radius: 4px;
    color: var(--muted-foreground);
    flex-shrink: 0;
  }
  .view-button {
    height: 21px;
    border-radius: 0;
  }
  .view-button + .view-button {
    border-left: 1px solid var(--border);
  }
  .view-button:hover,
  .icon-button:hover,
  :global(.editor-more:hover) {
    background: var(--muted);
    color: var(--foreground);
  }
  .view-button[aria-pressed='true'] {
    background: var(--sidebar-accent);
    color: var(--sidebar-accent-foreground);
    box-shadow: inset 0 0 0 1px var(--border);
  }
  button:focus-visible,
  input:focus-visible,
  :global(.editor-more:focus-visible) {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
  }
  button:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .unsaved:not(:disabled) {
    color: var(--brand-strong);
  }
  :global(.editor-menu [data-slot='dropdown-menu-checkbox-item-indicator']) {
    left: 6px;
    right: auto;
  }
  :global(.editor-menu [data-slot='dropdown-menu-checkbox-item']) {
    padding-left: 24px;
    padding-right: 6px;
  }
</style>
