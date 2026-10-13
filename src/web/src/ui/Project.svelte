<script lang="ts">
  import { onMount, tick, type Snippet } from 'svelte';
  import { projectLayoutKey, readProjectLayout } from '../lib/project-layout';
  import type { ObjectVersion } from '../lib/research-api';
  import type { Activity } from '../lib/history-api';
  import ProjectWorkbench from './ProjectWorkbench.svelte';
  import ProjectFiles from './ProjectFiles.svelte';
  import ProjectOverview from './ProjectOverview.svelte';
  import ProjectSectionPanel from './ProjectSectionPanel.svelte';
  import ProjectObjectPanel from './ProjectObjectPanel.svelte';
  import LoadingState from './LoadingState.svelte';
  import * as Alert from '../lib/components/ui/alert';
  import { Button, buttonVariants } from '../lib/components/ui/button';
  import { toStore } from 'svelte/store';
  import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
  import * as Sheet from '../lib/components/ui/sheet';
  import {
    Settings,
    PanelLeftOpen,
    PanelRight,
    PanelRightOpen,
    Maximize2,
    Minimize2,
    FileText,
    Files,
    Plug,
    Map as MapIcon,
    MessagesSquare,
    ArrowRight,
    History,
    LayoutDashboard,
    SquarePen,
    ChevronDown,
    MessageSquare,
  } from '@lucide/svelte';
  import { projectContext, explain } from '../svelte-lib/context';
  import { accountHref } from '../lib/account-navigation';
  import { canWriteResearch, restrictionMessage } from '../lib/access';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import type { ProjectMap } from '../lib/project-map';
  import ProjectMapPanel from './ProjectMapPanel.svelte';
  let mapData = $state<ProjectMap>();
  let mapPanelTab = $state('body');
  let mapObjectId = $state(page.url.searchParams.get('object') ?? '');
  $effect(() => {
    const id = page.url.searchParams.get('object');
    if (page.url.pathname.endsWith('/map') && id) mapObjectId = id;
  });
  const mapFocus = $derived(mapData?.objects.find((object) => object.id === mapObjectId));
  import ProductHeader from './ProductHeader.svelte';
  let { projectId, path }: { projectId: string; path: string } = $props();
  const { api, agents, auth, capabilities } = projectContext();
  let leftClosed = $state(false);
  let rightClosed = $state(false);
  let maximized = $state(false);
  async function collapseRightPanel() {
    rightClosed = true;
    maximized = false;
    await tick();
    document.querySelector<HTMLButtonElement>('.product-project-expand-panel')?.focus();
  }
  async function expandRightPanel() {
    rightClosed = false;
    await tick();
    document.querySelector<HTMLButtonElement>('.room-panel-toggle')?.focus();
  }
  let selectedResearch = $state<{ version: ObjectVersion; searchResult: boolean }>();
  function inspectResearch() {
    if (matchMedia('(max-width: 760px)').matches) mobileRight = true;
    else rightClosed = false;
  }
  let selectedActivity = $state<Activity>();
  let objectPanelTab = $state('body');
  let layoutReady = $state(false);
  onMount(() => {
    try {
      const saved = readProjectLayout(localStorage);
      leftWidth = saved.leftWidth;
      rightShare = saved.rightShare;
      leftClosed = saved.leftClosed;
      rightClosed = saved.rightClosed;
    } catch {
      /* Storage can be unavailable in private browsing. */
    }
    layoutReady = true;
  });
  $effect(() => {
    const saved = { leftWidth, rightShare, leftClosed, rightClosed };
    if (layoutReady) {
      try {
        localStorage.setItem(projectLayoutKey, JSON.stringify(saved));
      } catch {
        /* Keep in-memory controls usable. */
      }
    }
  });
  $effect(() => {
    void projectId;
    void section;
    selectedResearch = undefined;
    selectedActivity = undefined;
  });
  let leftWidth = $state(280);
  let roomWidth = $state(0);
  let rightShare = $state(0.4);
  const availableWidth = $derived(
    Math.max(0, roomWidth - (leftClosed ? 64 : leftWidth) - (leftClosed ? 0 : 8) - 8),
  );
  const section = $derived(path.split('/')[3] ?? 'overview');
  let filesEnabled = $state(false);
  let fileNavigatorWidth = $state(280);
  const rightWidth = $derived(filesEnabled ? fileNavigatorWidth : availableWidth * rightShare);
  function setRightWidth(width: number) {
    if (filesEnabled) fileNavigatorWidth = Math.max(220, Math.min(440, width));
    else if (availableWidth > 0) rightShare = Math.max(0.2, Math.min(0.6, width / availableWidth));
  }
  let mobileLeft = $state(false);
  let mobileRight = $state(false);
  let sessionsOpen = $state(true);
  let resizing = $state<{ side: 'left' | 'right'; x: number; width: number }>();
  function resize(event: PointerEvent) {
    if (!resizing) return;
    const value =
      resizing.width + (event.clientX - resizing.x) * (resizing.side === 'left' ? 1 : -1);
    if (resizing.side === 'left') leftWidth = Math.max(216, Math.min(340, value));
    else setRightWidth(value);
  }
  function resizeKey(event: KeyboardEvent, side: 'left' | 'right') {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const delta = (event.key === 'ArrowRight' ? 8 : -8) * (side === 'left' ? 1 : -1);
    if (side === 'left') leftWidth = Math.max(216, Math.min(340, leftWidth + delta));
    else setRightWidth(rightWidth + delta);
  }
  const project = createQuery(
    toStore(() => ({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId) })),
  );
  const selectedId = $derived(path.split('/')[4]);
  const rightPanelUnavailable = $derived(
    !filesEnabled && section === 'sessions' && (!selectedId || selectedId === 'new'),
  );
  const rightPanelVisible = $derived(!rightClosed && !rightPanelUnavailable);
  const rightPanelTitle = $derived(
    filesEnabled
      ? 'File navigator'
      : (section === 'map' && mapFocus) ||
          (section === 'objects' && selectedId) ||
          (section === 'research' && selectedResearch)
        ? 'Focused Object'
        : section === 'activity' && selectedActivity
          ? 'Submission'
          : section === 'sessions'
            ? 'Chat settings'
            : 'Right Panel',
  );
  const executionEnabled = $derived(capabilities?.enabled('agent_execution') ?? false);
  const nav = [
    ['overview', 'Overview', LayoutDashboard],
    ['research', 'Research objects', Files],
    ['map', 'Map', MapIcon],
    ['activity', 'Activity', History],
    ['files', 'Files', FileText],
  ] as const;
  const member = $derived(auth.signedIn && Boolean($project.data?.current_user_role));
  const visibleNav = $derived(
    nav.filter(
      ([id]) => ['overview', 'research', 'records', 'map', 'activity'].includes(id) || member,
    ),
  );
  const canWrite = $derived(
    member && $project.data
      ? canWriteResearch($project.data.current_user_role, Boolean($project.data.archived_at))
      : false,
  );
  const canManage = $derived(member && $project.data?.current_user_role === 'OWNER');
  const canPublish = $derived(
    Boolean(member && $project.data?.current_user_role === 'OWNER' && !$project.data.archived_at),
  );
  const sessions = createInfiniteQuery(
    toStore(() => ({
      queryKey: ['sessions', projectId],
      enabled: canWrite,
      initialPageParam: undefined as string | undefined,
      queryFn: ({ pageParam }: { pageParam: string | undefined }) =>
        agents.listSessions(projectId, pageParam),
      getNextPageParam: (p: { nextCursor?: string }) => p.nextCursor,
    })),
  );
  const visibleSessions = $derived(
    ($sessions.data?.pages.flatMap((p) => p.items) ?? []).slice(0, 5),
  );
  let projectView = $state({ href: '', label: 'Overview' });
  $effect(() => {
    if (section !== 'files')
      projectView = {
        href: page.url.pathname + page.url.search,
        label:
          nav.find(([id]) => id === section)?.[1] ??
          (section === 'sessions'
            ? selectedId && selectedId !== 'new'
              ? 'Chat'
              : 'Sessions'
            : section === 'objects'
              ? 'Research object'
              : section === 'settings'
                ? 'Settings'
                : 'Project'),
      };
  });
  function openFileEditor() {
    mobileRight = false;
    maximized = false;
    if (section !== 'files') void goto(`/projects/${projectId}/files`);
  }
</script>

<svelte:head><title>{$project.data?.name ?? 'Project'} · Polycolab</title></svelte:head>

{#if member && $project.data}
  {#if $project.data.workspace_mode === 'linear'}{#await import('./LinearWorkbench.svelte')}<LoadingState
        >Opening shared project…</LoadingState
      >{:then module}<module.default
        project={$project.data}
        {path}
      />{/await}{:else}<ProjectWorkbench project={$project.data} {path} />{/if}
{:else}
  <ProductHeader
    {auth}
    active="projects"
    projectName={$project.data?.name ?? 'Research project'}
    projectSidebarWidth={leftClosed ? 64 : leftWidth}
    projectRightWidth={maximized
      ? rightPanelUnavailable
        ? 0
        : Math.max(0, roomWidth - (leftClosed ? 64 : leftWidth) - (leftClosed ? 0 : 8))
      : rightPanelVisible
        ? rightWidth
        : 0}
    projectRightHandle={!rightPanelVisible || maximized ? 0 : 8}
    projectPanelMaximized={maximized && !rightPanelUnavailable}
    projectResizing={resizing?.side === 'left'}
    sidebarCollapsed={leftClosed}
    onToggleSidebar={() => (leftClosed = !leftClosed)}
    onToggleRightPanel={rightClosed && !rightPanelUnavailable ? expandRightPanel : undefined}
    projectSettingsHref={canManage ? `/projects/${projectId}/settings` : undefined}
    projectSettingsActive={section === 'settings'}
    projectAgentConnectHref={`/projects/${projectId}/agent-connect`}
    projectAgentConnectActive={section === 'agent-connect'}
  />
  {#if $project.isPending}<main id="main" class="page" tabindex="-1">
      <LoadingState>Opening research project…</LoadingState>
    </main>{:else if $project.isError || !$project.data}<main id="main" class="page" tabindex="-1">
      <h1>Project unavailable</h1>
      <Alert.Root variant="destructive" role="alert">{explain($project.error)}</Alert.Root>
      <Button type="submit" onclick={() => $project.refetch()}>Retry</Button>
      <a href={`/projects/${projectId}`}>View public project</a>
      <a href="/projects">Return to your projects</a>
    </main>{:else}
    {#if member}
      <ProjectFiles
        {projectId}
        bind:enabled={filesEnabled}
        active={section === 'files'}
        onFileOpen={openFileEditor}
      >
        {#snippet projectTab()}
          <a
            class="project-view-tab"
            role="tab"
            aria-selected={section !== 'files'}
            href={projectView.href || `/projects/${projectId}`}>{projectView.label}</a
          >
        {/snippet}
        {#snippet children(editor, navigator, tabs)}{@render projectRoom(
            editor,
            navigator,
            tabs,
          )}{/snippet}
      </ProjectFiles>
    {:else}
      {@render projectRoom()}
    {/if}
  {/if}

  {#snippet projectRoom(fileEditor?: Snippet, fileNavigator?: Snippet, fileTabs?: Snippet)}
    {#if $project.data}
      <div class="room-mobile-toolbar" aria-label="Project panels">
        <Sheet.Root bind:open={mobileLeft}
          ><Sheet.Trigger
            class={buttonVariants({ variant: 'outline' })}
            aria-label="Open sessions navigation"
            ><PanelLeftOpen class="size-4 shrink-0" aria-hidden="true" /> Navigation</Sheet.Trigger
          ><Sheet.Content side="left" class="p-4" showCloseButton={false}
            ><Sheet.Title class="sr-only">Session navigation</Sheet.Title>{@render navigation()}
            <Sheet.Close class={buttonVariants({ variant: 'outline' })}
              >Close navigation</Sheet.Close
            ></Sheet.Content
          ></Sheet.Root
        >
        {#if !rightPanelUnavailable}<Sheet.Root bind:open={mobileRight}
            ><Sheet.Trigger class={buttonVariants({ variant: 'outline' })} aria-label="Open panel"
              >{rightPanelTitle}
              <PanelRightOpen class="size-4 shrink-0" aria-hidden="true" /></Sheet.Trigger
            ><Sheet.Content side="right" class="p-4" showCloseButton={false}
              ><Sheet.Title class="sr-only">{rightPanelTitle}</Sheet.Title>{@render toolsPanel(
                'mobile',
                fileNavigator,
              )}
              <Sheet.Close class={buttonVariants({ variant: 'outline' })}>Close tools</Sheet.Close
              ></Sheet.Content
            ></Sheet.Root
          >{/if}
      </div>
      <div
        class="research-room"
        bind:clientWidth={roomWidth}
        class:room-maximized={maximized && !rightPanelUnavailable}
        class:room-resizing={Boolean(resizing)}
        style={`--room-left:${leftClosed ? 64 : leftWidth}px;--room-left-handle:${leftClosed ? 0 : 8}px;--room-right:${rightPanelVisible ? rightWidth : 0}px;--room-right-handle:${rightPanelVisible ? 8 : 0}px`}
      >
        <div class="room-desktop-left">{@render navigation(leftClosed)}</div>
        {#if !leftClosed}
          <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions (keyboard-adjustable splitter follows the ARIA separator pattern) -->
          <div
            class="room-resizer"
            role="separator"
            aria-label="Resize session navigation"
            aria-orientation="vertical"
            aria-valuemin="216"
            aria-valuemax="340"
            aria-valuenow={leftWidth}
            tabindex={0}
            onpointerdown={(event) => {
              event.preventDefault();
              resizing = { side: 'left', x: event.clientX, width: leftWidth };
            }}
            onkeydown={(event) => resizeKey(event, 'left')}
          ></div>
        {/if}
        <section
          class="room-center"
          aria-label="Research workbench"
          hidden={maximized && !rightPanelUnavailable}
        >
          {@render fileTabs?.()}
          <main
            id="main"
            class="content room-content"
            class:files-content={section === 'files'}
            tabindex="-1"
          >
            {#if section !== 'overview' && section !== 'files'}{@render accessNotice()}{/if}
            {#if fileEditor && section === 'files'}
              {@render fileEditor()}
            {:else if section === 'objects' && selectedId && !member}
              {#await import('./PublicProjects.svelte') then module}{#key selectedId}<module.default
                    {projectId}
                    objectId={selectedId}
                    embedded
                  />{/key}{/await}
            {:else if section === 'objects' && selectedId}
              {#await import('./Document.svelte')}<LoadingState>
                  Opening document…
                </LoadingState>{:then module}{#key selectedId}<module.default
                    {projectId}
                    objectId={selectedId}
                    {canWrite}
                  />{/key}{/await}
            {:else if section === 'overview' || section === 'research'}
              {#if section === 'overview'}<ProjectOverview
                  name={$project.data.name}
                  description={$project.data.description}
                  visibility={$project.data.visibility}
                  role={$project.data.current_user_role}
                />
              {:else}
                {#await import('./ResearchList.svelte')}<LoadingState>
                    Loading research…
                  </LoadingState>{:then module}<module.default
                    {projectId}
                    {canWrite}
                    publicRead={!member}
                    bind:selected={selectedResearch}
                    oninspect={inspectResearch}
                  />{/await}{/if}
            {:else if section === 'records'}
              {#await import('./ProjectRecords.svelte')}<LoadingState
                  >Loading research…</LoadingState
                >
              {:then module}{#key selectedId}<module.default
                    {projectId}
                    {canWrite}
                    {canPublish}
                    publicRead={!member}
                    publicProject={$project.data.visibility === 'PUBLIC'}
                    revisionId={selectedId}
                  />{/key}{/await}
            {:else if section === 'references' && member}
              {#await import('./References.svelte')}<LoadingState
                  >Loading pinned research…</LoadingState
                >
              {:then module}<module.default {projectId} {canWrite} />{/await}
            {:else if section === 'activity'}
              {#await import('./ProjectActivity.svelte')}<LoadingState
                  >Loading activity…</LoadingState
                >
              {:then module}<module.default
                  {projectId}
                  publicRead={!member}
                  bind:selected={selectedActivity}
                  oninspect={() => {
                    if (matchMedia('(max-width: 760px)').matches) mobileRight = true;
                    else rightClosed = false;
                  }}
                />{/await}
            {:else if section === 'map'}
              {#await import('./Graph.svelte')}<LoadingState>
                  Loading project map…
                </LoadingState>{:then module}<module.default
                  {projectId}
                  publicRead={!member}
                  bind:objectId={mapObjectId}
                  initialFocusId={page.url.searchParams.get('object') ?? undefined}
                  onreview={(id) => {
                    mapObjectId = id;
                    mapPanelTab = 'reviews';
                    if (matchMedia('(max-width: 760px)').matches) mobileRight = true;
                    else rightClosed = false;
                  }}
                  ondata={(data) => (mapData = data)}
                />{/await}
            {:else if section === 'sessions'}
              {#if canWrite}{#await import('./Sessions.svelte')}<LoadingState>
                    Opening private sessions…
                  </LoadingState>{:then module}{#key selectedId}<module.default
                      {projectId}
                      sessionId={selectedId === 'new' ? undefined : selectedId}
                    />{/key}{/await}{:else}<h1>Private sessions</h1>
                <p>Agent sessions are available to active contributors and owners.</p>{/if}
            {:else if section === 'agent-connect'}
              {#await import('./ProjectAgentConnect.svelte')}<LoadingState
                  >Loading connection guide…</LoadingState
                >
              {:then module}<module.default
                  {projectId}
                  projectName={$project.data.name}
                  signedIn={auth.signedIn}
                  {canWrite}
                />{/await}
            {:else if section === 'proposals'}
              {#if canWrite}{#await import('./Proposals.svelte')}<LoadingState>
                    Opening proposal review…
                  </LoadingState>{:then module}{#key selectedId}<module.default
                      {projectId}
                      proposalId={selectedId}
                    />{/key}{/await}{:else}<h1>Proposal review unavailable</h1>
                <p>Review requires an active contributor or owner role.</p>{/if}
            {:else if section === 'verification' && member}
              {#await import('./VerificationProject.svelte')}<LoadingState>
                  Opening verification jobs…
                </LoadingState>{:then module}{#key selectedId}<module.default
                    {projectId}
                    jobId={selectedId}
                    {canWrite}
                  />{/key}{/await}
            {:else if section === 'settings' && canManage}
              {#await import('./Settings.svelte')}<LoadingState>
                  Opening settings…
                </LoadingState>{:then module}<module.default project={$project.data} />{/await}
            {:else}<h1>Page not found</h1>{/if}
          </main>
        </section>
        {#if rightPanelVisible}
          <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions (keyboard-adjustable splitter follows the ARIA separator pattern) -->
          <div
            class="room-resizer"
            role="separator"
            aria-label="Resize panel"
            aria-orientation="vertical"
            aria-valuemin={filesEnabled ? 220 : 20}
            aria-valuemax={filesEnabled ? 440 : 60}
            aria-valuenow={filesEnabled ? fileNavigatorWidth : Math.round(rightShare * 100)}
            aria-valuetext={filesEnabled
              ? `${fileNavigatorWidth} pixels`
              : `${Math.round(rightShare * 100)}% of the space beside navigation`}
            tabindex={0}
            onpointerdown={(event) => {
              event.preventDefault();
              resizing = { side: 'right', x: event.clientX, width: rightWidth };
            }}
            onkeydown={(event) => resizeKey(event, 'right')}
          ></div>
        {/if}
        {#if rightPanelVisible}<aside class="room-desktop-right" aria-label={rightPanelTitle}>
            <header class="room-tools-header">
              <span>{rightPanelTitle}</span><Button
                type="button"
                variant="ghost"
                size="icon-sm"
                class="room-panel-toggle"
                aria-label="Collapse panel"
                aria-expanded="true"
                title="Collapse panel"
                onclick={collapseRightPanel}
              >
                <PanelRight class="size-4 shrink-0" aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={maximized ? 'Restore panel' : 'Maximize panel'}
                onclick={() => (maximized = !maximized)}
                >{#if maximized}<Minimize2
                    class="size-4 shrink-0"
                    aria-hidden="true"
                  />{:else}<Maximize2 class="size-4 shrink-0" aria-hidden="true" />{/if}</Button
              >
            </header>
            {@render toolsPanel('desktop', fileNavigator)}
          </aside>{/if}
      </div>
    {/if}
  {/snippet}
{/if}

<svelte:window onpointermove={resize} onpointerup={() => (resizing = undefined)} />

{#snippet navigation(compact = false)}
  <aside
    class="room-navigation"
    class:room-navigation-compact={compact}
    aria-label="Session navigation"
  >
    <nav aria-label="Project sections">
      {#if executionEnabled && canWrite}<Button
          variant="ghost"
          class="room-nav-link"
          title={compact ? 'New chat' : undefined}
          href={`/projects/${projectId}/sessions/new`}
          aria-current={section === 'sessions' && selectedId === 'new' ? 'page' : undefined}
          onclick={() => (mobileLeft = false)}
          ><SquarePen class="size-4 shrink-0" aria-hidden="true" /><span class:sr-only={compact}
            >New chat</span
          ></Button
        >{/if}
      {#if canWrite}<Button
          variant="ghost"
          class="room-nav-link"
          title={compact ? 'All sessions' : undefined}
          href={`/projects/${projectId}/sessions`}
          aria-current={section === 'sessions' && !selectedId ? 'page' : undefined}
          onclick={() => (mobileLeft = false)}
          ><MessagesSquare class="size-4 shrink-0" aria-hidden="true" /><span
            class:sr-only={compact}>All sessions</span
          ></Button
        >{/if}
      {#each visibleNav as [id, label, Icon] (id)}
        {@render navigationLink(id, label, Icon, compact)}
      {/each}
    </nav>
    {#if canWrite}<div class="room-session-heading">
        <button
          type="button"
          class="room-session-toggle"
          title={compact ? 'Recent sessions' : undefined}
          aria-expanded={sessionsOpen && !compact}
          onclick={() => {
            if (compact) {
              leftClosed = false;
              sessionsOpen = true;
            } else sessionsOpen = !sessionsOpen;
          }}
          ><span class:sr-only={compact}>Recent sessions</span><ChevronDown
            class={`room-session-chevron size-4 shrink-0 ${sessionsOpen ? '' : 'room-session-chevron-closed'}`}
            aria-hidden="true"
          /></button
        >
      </div>
      {#if !compact && sessionsOpen}
        <div class="room-session-list">
          {#each visibleSessions as session (session.id)}<a
              href={`/projects/${projectId}/sessions/${session.id}`}
              onclick={() => (mobileLeft = false)}
              aria-current={section === 'sessions' && selectedId === session.id
                ? 'page'
                : undefined}>{session.title || session.agent_display_name}</a
            >{/each}
          {#if $sessions.isPending}<p class="muted">
              Loading sessions…
            </p>{:else if $sessions.isError}<Button
              type="submit"
              variant="outline"
              class=""
              onclick={() => $sessions.refetch()}>Retry sessions</Button
            >{:else if !visibleSessions.length}<div class="room-session-empty">
              <span class="room-session-empty-icon">
                <MessageSquare class="size-4" aria-hidden="true" />
              </span>
              <strong>No sessions yet.</strong>
              <p>Your recent chats will appear here once you start a conversation.</p>
            </div>{/if}
        </div>{/if}{/if}
    <nav class="room-navigation-footer" aria-label="Project tools">
      {@render navigationLink('agent-connect', 'Agent connect', Plug, compact)}
      {#if canManage}
        <Button
          variant="ghost"
          class="room-nav-link"
          href={`/projects/${projectId}/settings`}
          title={compact ? 'Project settings' : undefined}
          aria-current={section === 'settings' ? 'page' : undefined}
          onclick={() => (mobileLeft = false)}
          ><Settings class="size-4 shrink-0" aria-hidden="true" /><span class:sr-only={compact}
            >Project settings</span
          ></Button
        >
      {/if}
    </nav>
  </aside>
{/snippet}

{#snippet navigationLink(id: string, label: string, Icon: typeof FileText, compact: boolean)}
  <Button
    variant="ghost"
    class="room-nav-link"
    title={compact ? label : undefined}
    href={`/projects/${projectId}${id === 'overview' ? '' : `/${id}`}`}
    onclick={() => (mobileLeft = false)}
    aria-current={section === id || (id === 'research' && ['objects', 'records'].includes(section))
      ? 'page'
      : undefined}
    ><Icon class="size-4 shrink-0" aria-hidden="true" /><span class:sr-only={compact}>{label}</span
    ></Button
  >
{/snippet}

{#snippet toolsPanel(placement: 'desktop' | 'mobile', fileNavigator?: Snippet)}
  {#if fileNavigator}
    <div class="file-navigator-content">
      <div class="file-navigator-tree">{@render fileNavigator()}</div>
      {#if section !== 'files'}
        <section class="navigator-context" aria-label="Current view tools">
          {@render toolsPanel(placement)}
        </section>
      {/if}
    </div>
  {:else}
    <div class="room-tools-content">
      {#if section === 'map'}<ProjectMapPanel
          canReview={$project.data?.current_user_role === 'OWNER' ||
            $project.data?.current_user_role === 'CONTRIBUTOR'}
          {projectId}
          data={mapData}
          bind:activeTab={mapPanelTab}
          bind:objectId={mapObjectId}
        />{/if}
      {#if section === 'sessions'}
        <div class="project-chat-panel-host" data-chat-panel-host={placement}></div>
      {:else if section !== 'map' && $project.data}
        {#if section === 'objects' && selectedId}
          {#key selectedId}<ProjectObjectPanel
              {projectId}
              objectId={selectedId}
              publicRead={!member}
              bind:activeTab={objectPanelTab}
            />{/key}
        {:else}<ProjectSectionPanel
            project={$project.data}
            {section}
            bind:selected={selectedActivity}
            bind:selectedResearch
          />{/if}
      {/if}
      {#if member && section === 'objects' && selectedId}<nav
          aria-label="Object tools"
          class="room-object-tools"
        >
          {#each [['history', 'Version history'], ['discussion', 'Discussion']] as const as [panel, label] (panel)}<a
              aria-label={label}
              href={`/projects/${projectId}/objects/${selectedId}?panel=${panel}`}
              onclick={() => (mobileRight = false)}
              ><span>{label}</span><ArrowRight class="size-4 shrink-0" aria-hidden="true" /></a
            >{/each}
        </nav>{/if}
    </div>
  {/if}
{/snippet}

{#snippet accessNotice()}
  {#if $project.data?.archived_at}<p class="notice">
      This project is archived and cannot be changed.
    </p>
  {:else if !member}<p class="room-access-note">
      Contributing requires project membership.
      {#if !auth.signedIn}<Button
          variant="link"
          class="h-auto p-0"
          href={accountHref('signin', path)}>Sign in to contribute</Button
        >{/if}
    </p>
  {:else if !canWrite && $project.data}<p class="room-access-note">
      {restrictionMessage($project.data.current_user_role, false)}
    </p>{/if}
{/snippet}

<style>
  .file-navigator-content {
    height: calc(100% - var(--product-header-height));
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .file-navigator-tree {
    flex: 1;
    min-height: 200px;
    overflow: auto;
  }
  .navigator-context {
    max-height: 50%;
    overflow: auto;
    border-top: 1px solid var(--border);
  }
  .project-view-tab {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    padding: 0.6rem 0.85rem;
    border-right: 1px solid var(--border);
    border-top: 2px solid transparent;
    font-size: 0.75rem;
  }
  .project-view-tab[aria-selected='true'] {
    border-top-color: var(--primary);
    background: var(--background);
  }
  .files-content {
    padding: 0;
    max-width: none;
    height: 100%;
  }
</style>
