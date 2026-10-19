<script lang="ts">
  import { Plus, Upload, Check, X } from '@lucide/svelte';
  import { Button } from '../../../lib/components/ui/button';
  import FileExplorer from './FileExplorer.svelte';
  let {
    paths,
    selected = '',
    writable,
    loaded = true,
    onopen,
    oncreate,
    onupload,
  }: {
    paths: string[];
    selected?: string;
    writable: boolean;
    loaded?: boolean;
    onopen: (path: string) => void;
    oncreate: (path: string) => Promise<boolean>;
    onupload: (file: File) => Promise<void>;
  } = $props();
  let creating = $state(false);
  let name = $state('');
  let pending = $state(false);
  let input = $state<HTMLInputElement>();
  function focusInput(node: HTMLInputElement) {
    node.focus();
  }
  async function create() {
    if (pending || !name.trim()) return;
    pending = true;
    try {
      if (await oncreate(name)) {
        name = '';
        creating = false;
      }
    } finally {
      pending = false;
    }
  }
  async function upload(event: Event) {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;
    pending = true;
    try {
      await onupload(file);
    } finally {
      pending = false;
      if (input) input.value = '';
    }
  }
</script>

<div class="explorer-heading">
  <span>Files</span>
  <div>
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label="New file"
      disabled={!writable || pending}
      onclick={() => (creating = !creating)}><Plus size={14} /></Button
    >
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label="Upload a file"
      disabled={!writable || pending}
      onclick={() => input?.click()}><Upload size={14} /></Button
    >
  </div>
</div>
<input class="sr-only" type="file" aria-label="Upload file" bind:this={input} onchange={upload} />
{#if writable && creating}<form
    onsubmit={(event) => {
      event.preventDefault();
      void create();
    }}
  >
    <input
      aria-label="File path"
      bind:value={name}
      placeholder="notes.md"
      disabled={pending}
      use:focusInput
      onkeydown={(event) => {
        if (event.key === 'Escape' && !pending) {
          creating = false;
          name = '';
        }
      }}
    />
    <Button
      variant="ghost"
      size="icon-xs"
      type="submit"
      aria-label="Create file"
      disabled={!name.trim() || pending}><Check size={14} /></Button
    >
    <Button
      variant="ghost"
      size="icon-xs"
      aria-label="Cancel new file"
      disabled={pending}
      onclick={() => {
        creating = false;
        name = '';
      }}><X size={14} /></Button
    >
  </form>{/if}
{#if loaded}<FileExplorer {paths} {selected} {onopen} />{:else}<p class="muted">
    Loading files…
  </p>{/if}

<style>
  .explorer-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 2px 8px;
    gap: 4px;
    min-height: 28px;
    font-size: 12px;
  }
  .explorer-heading > div {
    display: flex;
  }
  form {
    padding: 2px 8px;
    display: flex;
    gap: 4px;
  }
  form input {
    min-width: 0;
    flex: 1;
    height: 24px;
    padding: 0 6px;
    border: 1px solid var(--border);
    border-radius: 3px;
    font-size: 12px;
    background: var(--background);
  }
  .muted {
    padding: 16px;
    color: var(--muted-foreground);
    font-size: 12px;
  }
</style>
