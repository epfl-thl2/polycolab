<script lang="ts">
  import type { Snippet } from 'svelte';
  import { chatPanelPortal } from '../../../lib/chat-panel-portal';
  let { active, children }: { active: boolean; children: Snippet } = $props();
  // A single mounted editor follows the desktop panel or mobile drawer, preserving drafts.
  function portal(node: HTMLElement, visible: boolean) {
    return chatPanelPortal(node, visible, 'data-file-panel-host');
  }
</script>

<div class="sidebar-file" use:portal={active}>{@render children()}</div>

<style>
  .sidebar-file {
    height: 100%;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .sidebar-file:global([hidden]) {
    display: none;
  }
</style>
