<script lang="ts">
  import type { Snippet } from 'svelte';
  import { Menu, PanelLeftOpen, PanelRightOpen, X } from '@lucide/svelte';
  import { Button } from '../../../lib/components/ui/button';
  import * as Sheet from '../../../lib/components/ui/sheet';
  let {
    projectName,
    leftTitle,
    leftLabel = `${leftTitle} panel`,
    rightLabel = 'Project tools',
    toolsAvailable = true,
    showProjectName = true,
    showTopBar = true,
    plainTopBar = false,
    leftClosed = $bindable(false),
    rightClosed = $bindable(false),
    leftWidth = $bindable(260),
    rightWidth = $bindable(280),
    navigation,
    left,
    toolbar,
    children,
    right,
    notice,
  }: {
    projectName: string;
    leftTitle: string;
    leftLabel?: string;
    rightLabel?: string;
    toolsAvailable?: boolean;
    showProjectName?: boolean;
    showTopBar?: boolean;
    plainTopBar?: boolean;
    leftClosed?: boolean;
    rightClosed?: boolean;
    leftWidth?: number;
    rightWidth?: number;
    navigation: Snippet<[boolean]>;
    left: Snippet<['desktop' | 'mobile']>;
    toolbar?: Snippet;
    children: Snippet;
    right: Snippet<['desktop' | 'mobile']>;
    notice?: Snippet;
  } = $props();
  let mobilePanel = $state<'navigation' | 'left' | 'tools'>();
  let drag = $state<{ side: 'left' | 'tools'; x: number; width: number }>();
  const toolsVisible = $derived(toolsAvailable && !rightClosed);
  export function closeDrawer() {
    mobilePanel = undefined;
  }
  export function showPanel(side: 'left' | 'tools') {
    if (side === 'left') leftClosed = false;
    else rightClosed = false;
    if (matchMedia('(max-width:760px)').matches) mobilePanel = side;
  }
  export function closePanel(side: 'left' | 'tools', placement: 'desktop' | 'mobile' = 'desktop') {
    if (placement === 'mobile') closeDrawer();
    else if (side === 'left') leftClosed = true;
    else rightClosed = true;
  }
  function setWidth(side: 'left' | 'tools', width: number) {
    if (side === 'left') leftWidth = Math.max(220, Math.min(360, width));
    else rightWidth = Math.max(240, Math.min(460, width));
  }
  function resize(event: PointerEvent) {
    if (drag)
      setWidth(drag.side, drag.width + (event.clientX - drag.x) * (drag.side === 'left' ? 1 : -1));
  }
  function resizeKey(event: KeyboardEvent, side: 'left' | 'tools') {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    setWidth(
      side,
      (side === 'left' ? leftWidth : rightWidth) +
        (event.key === 'ArrowRight' ? 8 : -8) * (side === 'left' ? 1 : -1),
    );
  }
</script>

<svelte:window
  onpointermove={resize}
  onpointerup={() => (drag = undefined)}
  onpointercancel={() => (drag = undefined)}
/>
<div class="project-shell">
  <div
    class="project-body"
    class:resizing={Boolean(drag)}
    style={`--left-width:${leftClosed ? 0 : leftWidth}px;--left-handle:${leftClosed ? 0 : 1}px;--tools-width:${toolsVisible ? rightWidth : 0}px;--tools-handle:${toolsVisible ? 1 : 0}px;--rail-width:56px`}
  >
    <div class="project-rail">{@render navigation(false)}</div>
    {#if !leftClosed}<aside class="project-agents" aria-label={leftLabel}>
        {@render left('desktop')}
      </aside>
      {@render splitter('left')}{/if}
    <section class="project-center" aria-label="Project workbench">
      {#if showTopBar}<div class="project-tabbar" class:plain-topbar={plainTopBar}>
          <div class="tabbar-controls" class:desktop-hidden={!leftClosed}>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Open navigation"
              onclick={() => (mobilePanel = 'navigation')}
              class="mobile-toggle"><Menu size={16} /></Button
            >
            {#if showProjectName}<span class="compact-project-name" title={projectName}
                >{projectName}</span
              >{/if}
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={leftClosed ? 'Show left panel' : 'Hide left panel'}
              onclick={() => showPanel('left')}><PanelLeftOpen size={16} /></Button
            >
          </div>
          {#if toolbar}{@render toolbar()}{/if}
          {#if toolsAvailable}<div
              class="tabbar-controls tools-toggle"
              class:desktop-hidden={!rightClosed}
            >
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={rightClosed ? 'Show tools' : 'Hide tools'}
                onclick={() => showPanel('tools')}><PanelRightOpen size={16} /></Button
              >
            </div>{/if}
        </div>
      {:else}
        <div class="edge-control navigation-control">
          <Button
            variant="outline"
            size="icon-sm"
            aria-label="Open navigation"
            onclick={() => (mobilePanel = 'navigation')}><Menu size={16} /></Button
          >
        </div>
        {#if toolsAvailable}<div class="edge-control tools-control" class:panel-open={!rightClosed}>
            <Button
              variant="outline"
              size="icon-sm"
              aria-label="Show tools"
              onclick={() => showPanel('tools')}><PanelRightOpen size={16} /></Button
            >
          </div>{/if}
      {/if}
      {#if notice}{@render notice()}{/if}
      <main id="main" class="project-main" tabindex="-1">{@render children()}</main>
    </section>
    {#if toolsVisible}{@render splitter('tools')}
      <aside class="project-tools" aria-label={rightLabel}>{@render right('desktop')}</aside>{/if}
  </div>
</div>
<Sheet.Root
  open={Boolean(mobilePanel)}
  onOpenChange={(open) => {
    if (!open) closeDrawer();
  }}
>
  <Sheet.Content
    side={mobilePanel === 'tools' ? 'right' : 'left'}
    class="p-0"
    showCloseButton={false}
  >
    <Sheet.Title class="sr-only"
      >{mobilePanel === 'tools'
        ? rightLabel
        : mobilePanel === 'left'
          ? leftTitle
          : 'Navigation'}</Sheet.Title
    >
    <div class="mobile-panel">
      {#if mobilePanel !== 'tools'}<header
          class="panel-heading"
          class:left-panel-controls={mobilePanel === 'left'}
        >
          {#if mobilePanel === 'navigation'}<span>Navigation</span>{/if}
          <Button variant="ghost" size="icon-sm" aria-label="Close drawer" onclick={closeDrawer}
            ><X size={14} /></Button
          >
        </header>{/if}
      {#if mobilePanel === 'navigation'}{@render navigation(
          true,
        )}{:else if mobilePanel === 'left'}{@render left(
          'mobile',
        )}{:else if mobilePanel === 'tools'}{@render right('mobile')}{/if}
    </div>
  </Sheet.Content>
</Sheet.Root>
{#snippet splitter(side: 'left' | 'tools')}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
  <div
    class="splitter"
    class:agents-splitter={side === 'left'}
    class:tools-splitter={side === 'tools'}
    role="separator"
    aria-label={side === 'left' ? 'Resize left panel' : 'Resize tools'}
    aria-orientation="vertical"
    aria-valuemin={side === 'left' ? 220 : 240}
    aria-valuemax={side === 'left' ? 360 : 460}
    aria-valuenow={side === 'left' ? leftWidth : rightWidth}
    tabindex="0"
    onpointerdown={(event) => {
      event.preventDefault();
      drag = { side, x: event.clientX, width: side === 'left' ? leftWidth : rightWidth };
    }}
    onkeydown={(event) => resizeKey(event, side)}
  ></div>
{/snippet}

<style>
  .project-shell,
  .mobile-panel {
    --project-nav-height: 32px;
  }
  .project-shell {
    display: flex;
    flex-direction: column;
    height: 100dvh;
    overflow: hidden;
    background: var(--background);
  }
  .compact-project-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .project-tabbar {
    display: flex;
    min-width: 0;
    flex-shrink: 0;
    background: var(--sidebar);
  }
  .project-tabbar.plain-topbar {
    background: #fff;
    color: #18181b;
    min-height: var(--project-nav-height);
  }
  .plain-topbar .tabbar-controls {
    border-bottom: 0;
  }
  .tools-toggle {
    margin-left: auto;
  }
  .project-tabbar > :global(.project-tab-strip) {
    flex: 1;
  }
  .tabbar-controls {
    height: var(--project-nav-height);
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 0 12px;
    border-bottom: 1px solid var(--border);
  }
  .compact-project-name {
    max-width: 180px;
    font-size: 12px;
    color: var(--brand-strong);
  }
  .desktop-hidden {
    display: none;
  }
  .project-body {
    display: grid;
    grid-template-columns:
      var(--rail-width) var(--left-width) var(--left-handle) minmax(0, 1fr)
      var(--tools-handle) var(--tools-width);
    flex: 1;
    min-height: 0;
  }
  .project-rail {
    grid-column: 1;
    grid-row: 1;
    position: relative;
    z-index: 20;
    min-height: 0;
  }
  .project-agents {
    grid-column: 2;
    grid-row: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    min-width: 0;
    background: var(--sidebar);
  }
  .edge-control {
    position: absolute;
    top: 50%;
    z-index: 20;
    transform: translateY(-50%);
  }
  .navigation-control {
    display: none;
    left: 4px;
  }
  .tools-control {
    right: 4px;
  }
  .tools-control.panel-open {
    display: none;
  }
  @media (max-width: 760px) {
    .navigation-control,
    .tools-control.panel-open {
      display: block;
    }
  }
  .project-center {
    position: relative;
    grid-column: 4;
    grid-row: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .project-main {
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow: hidden;
    position: relative;
  }
  .project-tools {
    grid-column: 6;
    grid-row: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--background);
  }
  .panel-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: var(--project-nav-height);
    min-height: var(--project-nav-height);
    box-sizing: border-box;
    padding: 0 12px;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
    font-weight: 600;
    line-height: 16px;
    background: var(--sidebar);
    flex-shrink: 0;
  }
  .left-panel-controls {
    justify-content: flex-end;
  }
  .splitter {
    cursor: col-resize;
    touch-action: none;
    background: var(--background);
    grid-row: 1;
  }
  .splitter:hover,
  .splitter:focus-visible {
    background: var(--primary);
    outline: 0;
  }
  .agents-splitter,
  .tools-splitter {
    position: relative;
    z-index: 1;
    background: var(--border);
  }
  .agents-splitter::before,
  .tools-splitter::before {
    content: '';
    position: absolute;
    inset: 0 -3px;
  }
  .agents-splitter {
    grid-column: 3;
  }
  .tools-splitter {
    grid-column: 5;
  }
  .mobile-panel {
    background: var(--background);
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  :global(.mobile-toggle) {
    display: none;
  }
  .tabbar-controls :global(button),
  .panel-heading :global(button) {
    width: 20px;
    height: 20px;
    min-height: 0;
    padding: 0;
  }
  .tabbar-controls :global(button svg),
  .panel-heading :global(button svg) {
    width: 14px;
    height: 14px;
  }
  @media (max-width: 1050px) and (min-width: 761px) {
    .project-body {
      grid-template-columns:
        var(--rail-width) min(var(--left-width), 220px) var(--left-handle)
        minmax(0, 1fr) var(--tools-handle) min(var(--tools-width), 240px);
    }
  }
  @media (max-width: 760px) {
    .project-body {
      display: flex;
    }
    .project-center {
      width: 100%;
    }
    .project-rail,
    .project-agents,
    .project-tools,
    .splitter {
      display: none;
    }
    .project-tabbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
    }
    .project-tabbar > :global(.project-tab-strip) {
      grid-row: 2;
      grid-column: 1 / -1;
    }
    .tabbar-controls {
      min-height: var(--project-nav-height);
      min-width: 0;
      display: flex;
      grid-row: 1;
    }
    .compact-project-name {
      max-width: none;
      flex: 1;
    }
    :global(.mobile-toggle) {
      display: inline-flex;
    }
  }
  .resizing {
    user-select: none;
    cursor: col-resize;
  }
</style>
