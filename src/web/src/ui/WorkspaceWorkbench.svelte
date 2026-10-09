<script lang="ts">
  import { onMount, tick, untrack, type Snippet } from 'svelte';
  import { goto, beforeNavigate } from '$app/navigation';
  import { page } from '$app/state';
  import {
    PanelLeftClose,
    PanelLeftOpen,
    PanelRightClose,
    PanelRightOpen,
    FolderOpen,
    GitBranch,
    Info,
    Menu,
    X,
  } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
  import * as Sheet from '../lib/components/ui/sheet';
  import { workspace, explain } from '../svelte-lib/context';
  import type { AgentSession } from '../lib/agent-sessions-api';
  import type { WorkspaceTask } from '../lib/workspace-tasks-api';
  import { canWriteResearch } from '../lib/access';
  import type { Project, ObjectVersion } from '../lib/research-api';
  import type { Activity } from '../lib/history-api';
  import type { WorkspaceMap } from '../lib/workspace-map';
  import {
    workspaceRouteTab,
    restoreWorkspaceTabs,
    type WorkspaceTab,
  } from '../lib/workspace-tabs';
  import WorkspaceNavigationRail from './WorkspaceNavigationRail.svelte';
  import WorkspaceTasks from './WorkspaceTasks.svelte';
  import WorkspaceTabStrip from './WorkspaceTabStrip.svelte';
  import BrandWordmark from './BrandWordmark.svelte';
  import WorkspaceFiles from './WorkspaceFiles.svelte';
  import WorkspacePage from './WorkspacePage.svelte';
  import WorkspaceMapPanel from './WorkspaceMapPanel.svelte';
  import WorkspaceObjectPanel from './WorkspaceObjectPanel.svelte';
  import WorkspaceSectionPanel from './WorkspaceSectionPanel.svelte';
  let { project, path }: { project: Project; path: string } = $props();
  const { auth, drafts, capabilities, tasks: taskApi, agents, query } = workspace();
  const projectId = $derived(project.id);
  const canWrite = $derived(
    canWriteResearch(project.current_user_role, Boolean(project.archived_at)),
  );
  const canChat = $derived(canWrite && Boolean(capabilities?.enabled('agent_execution')));
  let tabs = $state<WorkspaceTab[]>([]);
  let activeId = $state('');
  let ready = $state(false);
  let handledRoute = '';
  let agentsClosed = $state(false);
  let rightClosed = $state(false);
  let agentWidth = $state(260);
  let rightWidth = $state(280);
  let rightMode = $state<'explorer' | 'source-control' | 'details'>('explorer');
  let mobilePanel = $state<'navigation' | 'agents' | 'tools' | undefined>();
  let drag = $state<{ side: 'agents' | 'tools'; x: number; width: number }>();
  let filesEnabled = $state(false);
  let filesBusy = $state(false);
  let files = $state<WorkspaceFiles>();
  let fileItems = $state<{ id: string; label: string; path: string; dirty: boolean }[]>([]);
  let currentFileId = $state('');
  let workingBranch = $state('main');
  let knownTasks = $state.raw<Record<string, WorkspaceTask>>({});
  let contextError = $state('');
  let contextSwitching = false;
  let pendingBranch: Promise<boolean> | undefined;
  let routeVersion = 0;
  const selectedTask = $derived(
    Object.values(knownTasks).find((task) => task.branch === workingBranch),
  );
  const branchLabels = $derived(
    Object.fromEntries(Object.values(knownTasks).map((task) => [task.branch, task.title])),
  );
  let selectedResearch = $state<{ version: ObjectVersion; searchResult: boolean }>();
  let selectedActivity = $state<Activity>();
  let mapData = $state<WorkspaceMap>();
  let mapObjectId = $state('');
  let mapPanelTab = $state('body');
  let objectPanelTab = $state('body');
  const active = $derived(tabs.find((tab) => tab.id === activeId));
  const activeUrl = $derived(new URL(active?.href || path, 'http://workspace.local'));
  const section = $derived(activeUrl.pathname.split('/')[3] || 'overview');
  const entity = $derived(activeUrl.pathname.split('/')[4]);
  const fileView = $derived(
    active?.kind === 'diff' ? (active.id === 'diff:merge' ? 'merge' : 'history') : 'file',
  );
  const account = $derived(auth.account?.username || auth.user?.profile.sub);
  const storageKey = $derived(
    account ? `polycolab.workbench.v2:${account}:${projectId}` : undefined,
  );
  function navigate(href: string, replaceState = false) {
    mobilePanel = undefined;
    void goto(href, { noScroll: true, keepFocus: true, replaceState });
  }
  function newChat(taskId: string | null = selectedTask?.id || null) {
    const href = `/workspaces/${projectId}/sessions/new?draft=${crypto.randomUUID()}${taskId ? `&task=${encodeURIComponent(taskId)}` : ''}`;
    addRoute(href);
    navigate(href);
  }
  function cacheTasks(items: WorkspaceTask[]) {
    knownTasks = { ...knownTasks, ...Object.fromEntries(items.map((task) => [task.id, task])) };
    for (const task of items) query.setQueryData(['workspace-task', projectId, task.id], task);
  }
  async function readTask(id: string) {
    if (!taskApi) throw new Error('Tasks are unavailable');
    const task = await query.fetchQuery({
      queryKey: ['workspace-task', projectId, id],
      queryFn: () => taskApi.get(projectId, id),
      staleTime: 5000,
    });
    cacheTasks([task]);
    return task;
  }
  async function switchBranch(branch: string, version: number, routeDriven = false) {
    while (pendingBranch) {
      try {
        await pendingBranch;
      } catch {
        /* The initiating action reports the error. */
      }
    }
    if (version !== routeVersion) return false;
    if (branch === workingBranch) return true;
    contextSwitching = routeDriven;
    pendingBranch = files?.selectWorkspaceBranch(branch) || Promise.resolve(false);
    try {
      const selected = await pendingBranch;
      await tick();
      return selected && version === routeVersion;
    } finally {
      pendingBranch = undefined;
      contextSwitching = false;
    }
  }
  async function selectTask(task?: WorkspaceTask) {
    const version = ++routeVersion;
    contextError = '';
    try {
      if (!(await switchBranch(task?.branch || 'main', version))) return false;
      if (task) cacheTasks([task]);
      rightMode = 'explorer';
      mobilePanel = undefined;
      return true;
    } catch (error) {
      contextError = explain(error);
      return false;
    }
  }
  async function newTaskChat(task?: WorkspaceTask) {
    if (await selectTask(task)) newChat(task?.id || null);
  }
  function openSession(session: AgentSession) {
    query.setQueryData(['session', session.id], session);
    const href = `/workspaces/${projectId}/sessions/${session.id}`;
    if (page.url.pathname + page.url.search === href) void applyRoute(href, filesEnabled);
    else navigate(href);
  }
  function addRoute(href: string) {
    const tab = workspaceRouteTab(projectId, href);
    if (!tab) return;
    const existing = tabs.find((item) => item.id === tab.id);
    if (existing) {
      if (existing.href !== tab.href)
        tabs = tabs.map((item) => (item.id === tab.id ? { ...item, href: tab.href } : item));
    } else tabs = [...tabs, tab];
    activeId = tab.id;
  }
  onMount(() => {
    if (storageKey)
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
        tabs = restoreWorkspaceTabs(projectId, JSON.stringify(saved.tabs));
        agentsClosed = saved.agentsClosed === true;
        rightClosed = saved.rightClosed === true;
        if (typeof saved.agentWidth === 'number')
          agentWidth = Math.max(220, Math.min(360, saved.agentWidth));
        if (typeof saved.rightWidth === 'number')
          rightWidth = Math.max(240, Math.min(460, saved.rightWidth));
        if (['explorer', 'source-control', 'details'].includes(saved.rightMode))
          rightMode = saved.rightMode;
      } catch {
        /* Layout preferences are optional. */
      }
    ready = true;
    if (path === `/workspaces/${projectId}` || path === `/projects/${projectId}`) {
      const href = `/workspaces/${projectId}/${canChat ? 'sessions/new' : 'overview'}`;
      addRoute(href);
      navigate(href, true);
    }
  });
  $effect(() => {
    const href = page.url.pathname + page.url.search;
    const repositoryReady = filesEnabled;
    const repositoryBusy = filesBusy;
    if (!ready) return;
    untrack(() => {
      const routeKey = `${href}:${repositoryReady}`;
      if (handledRoute === routeKey) return;
      if (page.url.pathname.endsWith('/files') && repositoryBusy) return;
      handledRoute = routeKey;
      void applyRoute(href, repositoryReady);
    });
  });
  async function applyRoute(href: string, repositoryReady: boolean) {
    const version = ++routeVersion;
    const url = new URL(href, 'http://workspace.local');
    contextError = '';
    try {
      if (url.pathname === `/workspaces/${projectId}` || url.pathname === `/projects/${projectId}`)
        return;
      const routeTab = workspaceRouteTab(projectId, href);
      let targetBranch: string | undefined;
      if (routeTab?.kind === 'chat') {
        const sessionId = url.pathname.split('/')[4];
        const taskId =
          sessionId === 'new'
            ? url.searchParams.get('task')
            : (
                await query.fetchQuery({
                  queryKey: ['session', sessionId],
                  queryFn: () => agents.getSession(sessionId),
                  staleTime: 5000,
                })
              ).task_id;
        targetBranch = taskId ? (await readTask(taskId)).branch : 'main';
      } else if (url.pathname.endsWith('/files')) {
        targetBranch = url.searchParams.get('branch') || workingBranch;
      }
      if (version !== routeVersion) return;
      if (targetBranch) {
        const selected = await switchBranch(targetBranch, version, true);
        if (version !== routeVersion) return;
        if (!selected) {
          if (active) navigate(active.href, true);
          return;
        }
      }
      if (url.pathname.endsWith('/files')) {
        const view = url.searchParams.get('view');
        const id = url.searchParams.get('tab');
        if (view === 'history' || view === 'merge') {
          openFileView(view, false);
          if (view === 'history' && repositoryReady) void files?.loadWorkspaceHistory();
        } else if (id && fileItems.some((item) => item.id === id)) {
          files?.selectWorkspaceFile(id);
          activeId = `file:${id}`;
        } else if (url.searchParams.get('file') && repositoryReady) {
          const name = url.searchParams.get('file')!;
          const existing = fileItems.find((item) => item.path === name);
          if (existing) {
            files?.selectWorkspaceFile(existing.id);
            activeId = `file:${existing.id}`;
          } else void files?.openWorkspaceFile(name);
        } else if (currentFileId) activeId = `file:${currentFileId}`;
        else addRoute(href);
      } else addRoute(href);
    } catch (error) {
      if (version !== routeVersion) return;
      contextError = explain(error);
      if (active) navigate(active.href, true);
    }
  }
  $effect(() => {
    const saved = {
      tabs: tabs
        .filter((tab) => tab.kind !== 'file' && tab.kind !== 'diff')
        .map((tab) => ({ href: tab.href })),
      agentsClosed,
      rightClosed,
      agentWidth,
      rightWidth,
      rightMode,
    };
    if (ready && storageKey)
      try {
        localStorage.setItem(storageKey, JSON.stringify(saved));
      } catch {
        /* Keep the current session usable. */
      }
  });
  function syncFiles(items: typeof fileItems, id: string) {
    const previousHref = tabs.find((tab) => tab.id === activeId)?.href;
    const staleDiff = (tab: WorkspaceTab) =>
      tab.kind === 'diff' &&
      new URL(tab.href, 'http://workspace.local').searchParams.get('branch') !== workingBranch;
    const lostActive =
      (activeId.startsWith('file:') && !items.some((item) => `file:${item.id}` === activeId)) ||
      Boolean(active && staleDiff(active));
    fileItems = items;
    currentFileId = id;
    tabs = tabs
      .filter((tab) => !staleDiff(tab))
      .filter((tab) => tab.kind !== 'file' || items.some((item) => `file:${item.id}` === tab.id))
      .map((tab) => {
        const file = items.find((item) => `file:${item.id}` === tab.id);
        return file ? { ...tab, label: file.label, dirty: file.dirty, href: fileHref(file) } : tab;
      });
    const currentTab = tabs.find((tab) => tab.id === activeId);
    if (
      currentTab?.kind === 'file' &&
      previousHref !== currentTab.href &&
      page.url.pathname + page.url.search === previousHref
    )
      navigate(currentTab.href, true);
    if (lostActive && !contextSwitching) {
      const href = `/workspaces/${projectId}/files?branch=${encodeURIComponent(workingBranch)}`;
      addRoute(href);
      navigate(href);
    }
  }
  function fileHref(file: { id: string; path: string }) {
    return `/workspaces/${projectId}/files?${file.path ? `file=${encodeURIComponent(file.path)}` : `tab=${encodeURIComponent(file.id)}`}&branch=${encodeURIComponent(workingBranch)}`;
  }
  async function openFile(id?: string) {
    await tick();
    const selected = id || currentFileId;
    const file = fileItems.find((item) => item.id === selected);
    if (!file) {
      navigate(`/workspaces/${projectId}/files`);
      return;
    }
    const tabId = `file:${selected}`;
    const href = fileHref(file);
    tabs = tabs.filter((tab) => tab.id !== 'files:');
    if (!tabs.some((tab) => tab.id === tabId))
      tabs = [...tabs, { id: tabId, kind: 'file', label: file.label, dirty: file.dirty, href }];
    activeId = tabId;
    if (page.url.pathname + page.url.search !== href) navigate(href);
  }
  function openFileView(view: 'history' | 'merge', changeUrl = true) {
    const id = `diff:${view}`;
    const href = `/workspaces/${projectId}/files?view=${view}&branch=${encodeURIComponent(workingBranch)}`;
    if (!tabs.some((tab) => tab.id === id))
      tabs = [
        ...tabs,
        { id, kind: 'diff', label: view === 'history' ? 'File history' : 'Merge review', href },
      ];
    else tabs = tabs.map((tab) => (tab.id === id ? { ...tab, href } : tab));
    activeId = id;
    if (changeUrl && page.url.pathname + page.url.search !== href) navigate(href);
  }
  function selectTab(id: string) {
    const tab = tabs.find((item) => item.id === id);
    if (!tab) return;
    if (tab.kind === 'file' && !files?.selectWorkspaceFile(id.slice(5))) return;
    if (tab.kind === 'file') activeId = id;
    if (page.url.pathname + page.url.search === tab.href) void applyRoute(tab.href, filesEnabled);
    else navigate(tab.href);
  }
  function updateTab(id: string, state: { label?: string; dirty: boolean }) {
    untrack(() => {
      const tab = tabs.find((item) => item.id === id);
      if (tab && (tab.dirty !== state.dirty || (state.label && state.label !== tab.label)))
        tabs = tabs.map((item) =>
          item.id === id ? { ...item, label: state.label || item.label, dirty: state.dirty } : item,
        );
    });
  }
  function created(oldId: string, id: string) {
    tabs = tabs.filter((tab) => tab.id !== oldId);
    navigate(`/workspaces/${projectId}/sessions/${id}`);
  }
  async function closeTab(id: string) {
    const tab = tabs.find((item) => item.id === id);
    if (!tab) return;
    if (tab.kind === 'file') {
      if (!files?.closeWorkspaceFile(id.slice(5))) return;
    } else if (tab.dirty && !confirm(`Discard unsaved changes in ${tab.label}?`)) return;
    if (tab.kind === 'object')
      drafts.delete(
        `${projectId}:${new URL(tab.href, 'http://workspace.local').pathname.split('/')[4]}`,
      );
    const index = tabs.findIndex((item) => item.id === id);
    tabs = tabs.filter((item) => item.id !== id);
    if (activeId === id) {
      const next = tabs[Math.min(index, tabs.length - 1)];
      if (next) selectTab(next.id);
      else {
        // Unmount even when the fallback is another New chat with the same route key.
        await tick();
        if (tabs.length) return;
        const href = `/workspaces/${projectId}/${canChat ? 'sessions/new' : 'overview'}`;
        addRoute(href);
        navigate(href);
      }
    }
  }
  function reorder(ids: string[]) {
    tabs = ids.flatMap((id) => {
      const tab = tabs.find((item) => item.id === id);
      return tab ? [tab] : [];
    });
  }
  function inspect() {
    rightMode = 'details';
    rightClosed = false;
    if (matchMedia('(max-width:760px)').matches) mobilePanel = 'tools';
  }
  beforeNavigate(({ to, cancel }) => {
    if (
      to &&
      [`/workspaces/${projectId}`, `/projects/${projectId}`].some(
        (root) => to.url.pathname === root || to.url.pathname.startsWith(`${root}/`),
      )
    )
      return;
    if (
      tabs.some((tab) => tab.dirty) &&
      !confirm('Leave this workspace and discard unsaved drafts?')
    )
      cancel();
  });
  function resize(event: PointerEvent) {
    if (!drag) return;
    const width = drag.width + (event.clientX - drag.x) * (drag.side === 'agents' ? 1 : -1);
    if (drag.side === 'agents') agentWidth = Math.max(220, Math.min(360, width));
    else rightWidth = Math.max(240, Math.min(460, width));
  }
  function resizeKey(event: KeyboardEvent, side: 'agents' | 'tools') {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const d = (event.key === 'ArrowRight' ? 8 : -8) * (side === 'agents' ? 1 : -1);
    if (side === 'agents') agentWidth = Math.max(220, Math.min(360, agentWidth + d));
    else rightWidth = Math.max(240, Math.min(460, rightWidth + d));
  }
</script>

<svelte:window
  onpointermove={resize}
  onpointerup={() => (drag = undefined)}
  onbeforeunload={(event) => {
    if (tabs.some((tab) => tab.dirty)) event.preventDefault();
  }}
/>
<WorkspaceFiles
  {projectId}
  bind:this={files}
  bind:enabled={filesEnabled}
  bind:busy={filesBusy}
  bind:branch={workingBranch}
  {branchLabels}
  active={active?.kind === 'file'}
  toolsView={rightMode === 'source-control' ? 'source-control' : 'explorer'}
  view={fileView}
  onFileOpen={openFile}
  onTabsChange={syncFiles}
  onOpenView={openFileView}
  onCloseView={(view) => closeTab(`diff:${view}`)}
>
  {#snippet children(editor, navigator)}
    <div class="workspace-shell">
      <div
        class="workspace-body"
        class:resizing={Boolean(drag)}
        style={`--agent-width:${!agentsClosed ? agentWidth : 0}px;--agent-handle:${!agentsClosed ? 5 : 0}px;--tools-width:${rightClosed ? 0 : rightWidth}px;--tools-handle:${rightClosed ? 0 : 5}px;--rail-width:56px`}
      >
        <div class="workspace-rail">
          <WorkspaceNavigationRail
            {projectId}
            {section}
            canManage={project.current_user_role === 'OWNER'}
            showBrand={agentsClosed}
            onNavigate={navigate}
          />
        </div>
        {#if !agentsClosed}<aside class="workspace-agents" aria-label="Task management">
            <header class="workspace-identity">
              {@render identity()}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Collapse tasks"
                onclick={() => (agentsClosed = true)}><PanelLeftClose size={15} /></Button
              >
            </header>
            <WorkspaceTasks
              {projectId}
              activeTaskId={selectedTask?.id}
              activeSessionId={section === 'sessions' ? entity : undefined}
              repositoryEnabled={filesEnabled}
              canCreate={canWrite}
              canReadChats={canWrite}
              {canChat}
              onSelectTask={selectTask}
              onNewChat={newTaskChat}
              onOpenSession={openSession}
              onTasksChange={cacheTasks}
            />
          </aside>
          <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
          <div
            class="splitter agents-splitter"
            role="separator"
            aria-label="Resize tasks"
            aria-orientation="vertical"
            aria-valuemin="220"
            aria-valuemax="360"
            aria-valuenow={agentWidth}
            tabindex="0"
            onpointerdown={(event) => {
              event.preventDefault();
              drag = { side: 'agents', x: event.clientX, width: agentWidth };
            }}
            onkeydown={(event) => resizeKey(event, 'agents')}
          ></div>{/if}
        <section class="workspace-center" aria-label="Workspace workbench">
          <div class="workspace-tabbar">
            <div class="tabbar-controls" class:desktop-hidden={!agentsClosed}>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Open navigation"
                onclick={() => (mobilePanel = 'navigation')}
                class="mobile-toggle"><Menu size={16} /></Button
              >
              <span class="compact-workspace-name" title={project.name}>{project.name}</span>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={agentsClosed ? 'Show tasks' : 'Hide tasks'}
                onclick={() => {
                  if (matchMedia('(max-width:760px)').matches) mobilePanel = 'agents';
                  else agentsClosed = false;
                }}><PanelLeftOpen size={16} /></Button
              >
            </div>
            <WorkspaceTabStrip
              {tabs}
              {activeId}
              onselect={selectTab}
              onclose={closeTab}
              onreorder={reorder}
              onnewchat={canChat && !selectedTask?.archived_at ? () => newChat() : undefined}
            />
            <div class="tabbar-controls tools-toggle" class:desktop-hidden={!rightClosed}>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={rightClosed ? 'Show tools' : 'Hide tools'}
                onclick={() => {
                  if (matchMedia('(max-width:760px)').matches) mobilePanel = 'tools';
                  else rightClosed = false;
                }}><PanelRightOpen size={16} /></Button
              >
            </div>
          </div>
          {#if contextError}<div class="context-error" role="alert">{contextError}</div>{/if}
          <main id="main" class="workspace-main" tabindex="-1">
            {#each tabs.filter((tab) => tab.kind !== 'file' && tab.kind !== 'diff' && tab.id !== 'files:') as tab (tab.id)}
              <div class="workspace-page" hidden={tab.id !== activeId}>
                <WorkspacePage
                  {project}
                  href={tab.href}
                  active={tab.id === activeId}
                  onState={(state) => updateTab(tab.id, state)}
                  onCreated={(id) => created(tab.id, id)}
                  onInspect={inspect}
                  bind:selectedResearch
                  bind:selectedActivity
                  bind:mapData
                  bind:mapObjectId
                  bind:mapPanelTab
                />
              </div>
            {/each}
            <div
              class="workspace-file-page"
              hidden={active?.kind !== 'file' && active?.kind !== 'diff' && active?.id !== 'files:'}
            >
              {@render editor()}
            </div>
          </main>
        </section>
        {#if !rightClosed}
          <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
          <div
            class="splitter tools-splitter"
            role="separator"
            aria-label="Resize tools"
            aria-orientation="vertical"
            aria-valuemin="240"
            aria-valuemax="460"
            aria-valuenow={rightWidth}
            tabindex="0"
            onpointerdown={(event) => {
              event.preventDefault();
              drag = { side: 'tools', x: event.clientX, width: rightWidth };
            }}
            onkeydown={(event) => resizeKey(event, 'tools')}
          ></div>
          <aside class="workspace-tools" aria-label="Workspace tools">
            <header class="panel-heading">
              <span
                >{rightMode === 'explorer'
                  ? 'Explorer'
                  : rightMode === 'source-control'
                    ? 'Source control'
                    : 'Details'}</span
              ><Button
                variant="ghost"
                size="icon-sm"
                aria-label="Collapse tools"
                onclick={() => (rightClosed = true)}><PanelRightClose size={15} /></Button
              >
            </header>
            {@render tools('desktop', navigator)}
          </aside>
        {/if}
      </div>
    </div>
    <Sheet.Root
      open={Boolean(mobilePanel)}
      onOpenChange={(open) => {
        if (!open) mobilePanel = undefined;
      }}
      ><Sheet.Content
        side={mobilePanel === 'tools' ? 'right' : 'left'}
        class="p-0"
        showCloseButton={false}
      >
        <Sheet.Title class="sr-only"
          >{mobilePanel === 'tools'
            ? 'Workspace tools'
            : mobilePanel === 'agents'
              ? 'Tasks'
              : 'Navigation'}</Sheet.Title
        >
        <div class="mobile-panel">
          <header class="panel-heading" class:workspace-identity={mobilePanel !== 'tools'}>
            {#if mobilePanel !== 'tools'}{@render identity()}{:else}<span
                >{mobilePanel === 'tools'
                  ? 'Tools'
                  : mobilePanel === 'agents'
                    ? 'Tasks'
                    : 'Navigation'}</span
              >{/if}
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Close drawer"
              onclick={() => (mobilePanel = undefined)}><X size={16} /></Button
            >
          </header>
          {#if mobilePanel === 'navigation'}<WorkspaceNavigationRail
              {projectId}
              {section}
              canManage={project.current_user_role === 'OWNER'}
              expanded
              onNavigate={navigate}
            />
          {:else if mobilePanel === 'agents'}<WorkspaceTasks
              {projectId}
              activeTaskId={selectedTask?.id}
              activeSessionId={section === 'sessions' ? entity : undefined}
              repositoryEnabled={filesEnabled}
              canCreate={canWrite}
              canReadChats={canWrite}
              {canChat}
              onSelectTask={selectTask}
              onNewChat={newTaskChat}
              onOpenSession={openSession}
              onTasksChange={cacheTasks}
            />
          {:else if mobilePanel === 'tools'}{@render tools('mobile', navigator)}{/if}
        </div>
      </Sheet.Content></Sheet.Root
    >
  {/snippet}
</WorkspaceFiles>
{#snippet identity()}
  <div class="identity-text">
    <a class="workspace-brand" href="/workspaces" aria-label="Polycolab workspaces">
      <img src="/brand/polycolab-mark.png" alt="" />
      <BrandWordmark />
    </a>
    <span class="workspace-name" title={project.name}>{project.name}</span>
  </div>
{/snippet}
{#snippet tools(placement: 'desktop' | 'mobile', navigator?: Snippet)}
  <div class="tool-switcher" role="tablist" aria-label="Workspace tools">
    {#each [['explorer', 'Explorer', FolderOpen], ['source-control', 'Source control', GitBranch], ['details', 'Details', Info]] as const as [id, label, Icon] (id)}
      <button
        role="tab"
        aria-selected={rightMode === id}
        title={label as string}
        onclick={() => (rightMode = id as typeof rightMode)}
        ><Icon size={15} /><span>{label}</span></button
      >
    {/each}
  </div>
  <div class="tool-content">
    {#if rightMode !== 'details'}{#if navigator}{@render navigator()}{:else}<p class="tool-empty">
          {filesEnabled ? 'Loading files…' : 'File storage is unavailable for this workspace.'}
        </p>{/if}
    {:else if section === 'sessions'}<div data-chat-panel-host={placement}></div>
      {#if entity === 'new' || !entity}<p class="tool-empty">
          Choose an agent and customize the conversation in the chat composer.
        </p>{/if}
    {:else if section === 'map'}<WorkspaceMapPanel
        {projectId}
        canReview={canWrite}
        data={mapData}
        bind:objectId={mapObjectId}
        bind:activeTab={mapPanelTab}
      />
    {:else if section === 'objects' && entity}{#key entity}<WorkspaceObjectPanel
          {projectId}
          objectId={entity}
          publicRead={false}
          bind:activeTab={objectPanelTab}
        />{/key}
    {:else}<WorkspaceSectionPanel
        {project}
        {section}
        bind:selected={selectedActivity}
        bind:selectedResearch
      />{/if}
  </div>
{/snippet}

<style>
  .context-error {
    padding: 10px 16px;
    color: var(--destructive);
    background: var(--accent-soft);
    font-size: 12px;
  }
  .workspace-shell {
    display: flex;
    flex-direction: column;
    height: 100dvh;
    overflow: hidden;
    background: var(--background);
  }
  .workspace-identity {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    flex-shrink: 0;
    gap: 8px;
    padding: 17px 12px 15px;
    border-bottom: 1px solid var(--border);
    background: var(--sidebar);
  }
  .identity-text {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }
  .workspace-brand {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    color: var(--foreground);
    font-size: 19px;
    text-decoration: none;
  }
  .workspace-brand img {
    width: 25px;
    height: 25px;
  }
  .workspace-name {
    color: var(--brand-strong);
    font-size: 12px;
    font-weight: 500;
  }
  .workspace-name,
  .compact-workspace-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .workspace-tabbar {
    display: flex;
    min-width: 0;
    flex-shrink: 0;
    background: var(--sidebar);
  }
  .workspace-tabbar > :global(.workspace-tab-strip) {
    flex: 1;
  }
  .tabbar-controls {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 0 5px;
    border-bottom: 1px solid var(--border);
  }
  .compact-workspace-name {
    max-width: 180px;
    font-size: 12px;
    color: var(--brand-strong);
  }
  .desktop-hidden {
    display: none;
  }
  .workspace-body {
    display: grid;
    grid-template-columns:
      var(--rail-width) var(--agent-width) var(--agent-handle) minmax(0, 1fr)
      var(--tools-handle) var(--tools-width);
    flex: 1;
    min-height: 0;
  }
  .workspace-rail {
    grid-column: 1;
    grid-row: 1;
    position: relative;
    z-index: 20;
    min-height: 0;
  }
  .workspace-agents {
    grid-column: 2;
    grid-row: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    min-width: 0;
    background: var(--sidebar);
    border-right: 1px solid var(--border);
  }
  .workspace-center {
    grid-column: 4;
    grid-row: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .workspace-main {
    flex: 1;
    min-height: 0;
    min-width: 0;
    overflow: hidden;
    position: relative;
  }
  .workspace-page {
    height: 100%;
    overflow: auto;
    padding: 24px;
  }
  .workspace-file-page {
    height: 100%;
    min-height: 0;
  }
  .workspace-main [hidden] {
    display: none !important;
  }
  .workspace-tools {
    grid-column: 6;
    grid-row: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    border-left: 1px solid var(--border);
    background: color-mix(in srgb, var(--research-accent) 3%, var(--background));
  }
  .panel-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 38px;
    padding: 0 9px;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
    font-weight: 550;
    flex-shrink: 0;
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
  .agents-splitter {
    grid-column: 3;
  }
  .tools-splitter {
    grid-column: 5;
  }
  .tool-switcher {
    display: flex;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }
  .tool-switcher button {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    font-size: 10px;
    padding: 10px 3px;
    border-bottom: 2px solid transparent;
  }
  .tool-switcher button[aria-selected='true'] {
    color: var(--accent-strong);
    background: var(--accent-soft);
    border-bottom-color: var(--research-accent);
  }
  .tool-switcher button:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: -2px;
  }
  .tool-content {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .tool-content > :global(.explorer) {
    height: 100%;
  }
  .tool-empty {
    font-size: 12px;
    padding: 16px;
    color: var(--muted-foreground);
    line-height: 1.6;
  }
  .mobile-panel {
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  :global(.mobile-toggle) {
    display: none;
  }
  @media (max-width: 1050px) and (min-width: 761px) {
    .workspace-body {
      grid-template-columns:
        var(--rail-width) min(var(--agent-width), 220px) var(--agent-handle)
        minmax(0, 1fr) var(--tools-handle) min(var(--tools-width), 240px);
    }
  }
  @media (max-width: 760px) {
    .workspace-body {
      display: flex;
    }
    .workspace-center {
      width: 100%;
    }
    .workspace-rail,
    .workspace-agents,
    .workspace-tools,
    .splitter {
      display: none;
    }
    .workspace-page {
      padding: 16px;
    }
    .workspace-tabbar {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
    }
    .workspace-tabbar > :global(.workspace-tab-strip) {
      grid-row: 2;
      grid-column: 1 / -1;
    }
    .tabbar-controls {
      min-height: 40px;
      min-width: 0;
      display: flex;
      grid-row: 1;
    }
    .compact-workspace-name {
      max-width: none;
      flex: 1;
    }
    :global(.mobile-toggle) {
      display: inline-flex;
    }
  }
</style>
