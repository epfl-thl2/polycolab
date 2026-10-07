<script lang="ts">
  import { tick } from 'svelte';
  import {
    FileText,
    MessageSquare,
    BookOpen,
    GitCompare,
    LayoutDashboard,
    Plus,
    X,
  } from '@lucide/svelte';
  import type { WorkspaceTab } from '../lib/workspace-tabs';
  let {
    tabs,
    activeId,
    onselect,
    onclose,
    onreorder,
    onnewchat,
  }: {
    tabs: WorkspaceTab[];
    activeId: string;
    onselect: (id: string) => void;
    onclose: (id: string) => void;
    onreorder: (ids: string[]) => void;
    onnewchat?: () => void;
  } = $props();
  let dragged = $state('');
  async function key(event: KeyboardEvent, index: number) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const target =
      tabs[
        event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? tabs.length - 1
            : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
      ];
    if (target) {
      onselect(target.id);
      await tick();
      document.getElementById(`workspace-tab-${target.id}`)?.focus();
    }
  }
  function move(id: string, delta: number) {
    const ids = tabs.map((tab) => tab.id);
    const index = ids.indexOf(id);
    const next = index + delta;
    if (next < 0 || next >= ids.length) return;
    [ids[index], ids[next]] = [ids[next], ids[index]];
    onreorder(ids);
  }
</script>

<div class="workspace-tab-strip">
  <div class="workspace-tab-list" role="tablist" aria-label="Workspace tabs">
    {#each tabs as tab, index (tab.id)}
      {@const Icon =
        tab.kind === 'chat'
          ? MessageSquare
          : tab.kind === 'file'
            ? FileText
            : tab.kind === 'object'
              ? BookOpen
              : tab.kind === 'diff'
                ? GitCompare
                : LayoutDashboard}
      <div class="workspace-tab" class:active={activeId === tab.id}>
        <button
          role="tab"
          id={`workspace-tab-${tab.id}`}
          aria-selected={activeId === tab.id}
          tabindex={activeId === tab.id ? 0 : -1}
          title={tab.label}
          draggable="true"
          ondragstart={(event) => {
            dragged = tab.id;
            event.dataTransfer?.setData('text/x-workspace-tab', tab.id);
          }}
          ondragend={() => (dragged = '')}
          ondragover={(event) => {
            if (dragged) event.preventDefault();
          }}
          ondrop={(event) => {
            event.preventDefault();
            if (!dragged || dragged === tab.id) return;
            const ids = tabs.map((item) => item.id).filter((id) => id !== dragged);
            ids.splice(ids.indexOf(tab.id), 0, dragged);
            onreorder(ids);
            dragged = '';
          }}
          onclick={() => onselect(tab.id)}
          onkeydown={(event) => {
            if (event.altKey && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
              event.preventDefault();
              move(tab.id, event.key === 'ArrowLeft' ? -1 : 1);
            } else void key(event, index);
          }}
        >
          <Icon size={14} /><span>{tab.label}</span>{#if tab.dirty}<i aria-label="Unsaved changes"
            ></i>{/if}
        </button>
        <button class="close" aria-label={`Close ${tab.label}`} onclick={() => onclose(tab.id)}
          ><X size={12} /></button
        >
      </div>
    {/each}
  </div>
  {#if onnewchat}<button
      class="new-chat"
      aria-label="New chat tab"
      title="New chat"
      onclick={onnewchat}><Plus size={16} /></button
    >{/if}
</div>

<style>
  .workspace-tab-strip {
    display: flex;
    min-height: 39px;
    flex-shrink: 0;
    border-bottom: 1px solid var(--border);
    background: var(--sidebar);
    min-width: 0;
  }
  .workspace-tab-list {
    display: flex;
    overflow-x: auto;
    flex: 1;
    min-width: 0;
  }
  .workspace-tab {
    display: flex;
    flex-shrink: 0;
    max-width: 230px;
    border-right: 1px solid var(--border);
    border-top: 2px solid transparent;
  }
  .workspace-tab.active {
    border-top-color: var(--primary);
    background: var(--background);
    color: var(--brand-strong);
  }
  button[role='tab'] {
    display: flex;
    gap: 7px;
    align-items: center;
    padding: 9px 8px 9px 12px;
    font-size: 12px;
    min-width: 0;
  }
  button[role='tab'] span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  button :global(svg) {
    flex-shrink: 0;
    color: var(--muted-foreground);
  }
  .workspace-tab.active button :global(svg) {
    color: var(--primary);
  }
  i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--primary);
    flex-shrink: 0;
  }
  .close {
    padding: 5px;
    margin-right: 5px;
  }
  .new-chat {
    padding: 10px;
    flex-shrink: 0;
  }
  button:hover {
    background: var(--brand-soft);
  }
  button:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
  }
</style>
