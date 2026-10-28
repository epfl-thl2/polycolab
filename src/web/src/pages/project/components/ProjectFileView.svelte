<script lang="ts">
  import FeedbackToast from '../../../ui/FeedbackToast.svelte';
  let notice = $state('');
  import type { Snippet } from 'svelte';
  import ProjectEditorHeader from './ProjectEditorHeader.svelte';
  let {
    path,
    mode = $bindable('source'),
    enhanced = $bindable(true),
    wordWrap = $bindable(true),
    binary = false,
    writable = false,
    busy = false,
    dirty = false,
    status,
    download,
    onsave,
    onrename,
    ondelete,
    onerror,
    onreload,
    children,
  }: {
    path: string;
    mode?: 'source' | 'preview' | 'changes';
    enhanced?: boolean;
    wordWrap?: boolean;
    binary?: boolean;
    writable?: boolean;
    busy?: boolean;
    dirty?: boolean;
    status?: string;
    download: () => void;
    onsave: () => void;
    onrename: (path: string) => void;
    ondelete: () => void;
    onerror: (message: string) => void;
    onreload?: () => void;
    children: Snippet;
  } = $props();
  let name = $state('');
  let renaming = $state(false);
  $effect(() => {
    name = path;
    renaming = false;
  });
</script>

<div class="file-view">
  <ProjectEditorHeader
    bind:path={name}
    bind:mode
    bind:enhanced
    bind:wordWrap
    bind:renaming
    {binary}
    {writable}
    {busy}
    {dirty}
    saved={true}
    showChanges={false}
    {onsave}
    {ondelete}
    {onerror}
    {onreload}
    onnotice={(message) => (notice = message)}
    ondownload={download}
    onrename={() => {
      name = path;
      renaming = true;
    }}
    onrenamecommit={() => {
      if (name !== path) onrename(name);
      name = path;
    }}
  />
  <FeedbackToast message={notice} />
  {#if status}<div class="save-workspace" role="status">{status}</div>{/if}
  <div class="editor-content">{@render children()}</div>
</div>

<style>
  .file-view {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    height: 100%;
    background: var(--background);
  }
  .save-workspace {
    padding: 4px 12px;
    border-bottom: 1px solid var(--border);
    font-size: 11px;
    color: var(--muted-foreground);
  }
  .editor-content {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .editor-content :global(textarea) {
    flex: 1;
    min-height: 160px;
    padding: 12px;
    font: 12px/1.6 monospace;
    resize: none;
  }
</style>
