<script lang="ts">
  import { canonicalUiLocation } from '../lib/ui-location';
  import { SvelteMap } from 'svelte/reactivity';
  import { onMount, tick, untrack, type Snippet } from 'svelte';
  import { goto, beforeNavigate } from '$app/navigation';
  import { page } from '$app/state';
  import {
    PanelLeftOpen,
    PanelRightClose,
    PanelRightOpen,
    FolderOpen,
    GitBranch,
    Info,
    History,
    Menu,
    X,
  } from '@lucide/svelte';
  import { Button } from '../lib/components/ui/button';
  import * as Sheet from '../lib/components/ui/sheet';
  import * as Tooltip from '../lib/components/ui/tooltip';
  import { projectContext, explain } from '../svelte-lib/context';
  import type { ProjectTask } from '../lib/project-tasks-api';
  import { canWriteResearch } from '../lib/access';
  import type { Project, ObjectVersion } from '../lib/research-api';
  import type { Activity } from '../lib/history-api';
  import type { ProjectMap } from '../lib/project-map';
  import {
    projectRouteTab,
    isProjectLayoutPage,
    restoreProjectTabs,
    type ProjectTab,
  } from '../lib/project-tabs';
  import ProjectNavigationRail from './ProjectNavigationRail.svelte';
  import ProjectWorktrees from './ProjectWorktrees.svelte';
  import ProjectPanelHeader from './ProjectPanelHeader.svelte';
  import ProjectTabStrip from './ProjectTabStrip.svelte';
  import ProjectFiles from './ProjectFiles.svelte';
  import ProjectPage from './ProjectPage.svelte';
  import ProjectObjectPanel from './ProjectObjectPanel.svelte';
  import ProjectSectionPanel from './ProjectSectionPanel.svelte';
  let { project, path }: { project: Project; path: string } = $props();
  const { auth, drafts, capabilities, tasks: taskApi, agents, query } = projectContext();
  const projectId = $derived(project.id);
  const canWrite = $derived(
    canWriteResearch(project.current_user_role, Boolean(project.archived_at)),
  );
  const canChat = $derived(canWrite && Boolean(capabilities?.enabled('agent_execution')));
  let tabs = $state<ProjectTab[]>([]);
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
  let files = $state<ProjectFiles>();
  let fileItems = $state<
    { id: string; label: string; path: string; dirty: boolean; preview?: boolean }[]
  >([]);
  let currentFileId = $state('');
  let workingBranch = $state('main');
  let knownTasks = $state.raw<Record<string, ProjectTask>>({});
  let contextError = $state('');
  let contextSwitching = false;
  let pendingBranch: Promise<boolean> | undefined;
  let routeVersion = 0;
  const selectedWorktree = $derived(
    Object.values(knownTasks).find((item) => item.branch === workingBranch),
  );
  const branchLabels = $derived(
    Object.fromEntries(Object.values(knownTasks).map((task) => [task.branch, task.title])),
  );
  let selectedResearch = $state<{ version: ObjectVersion; searchResult: boolean }>();
  let researchCreationOpen = $state(false);
  let researchCountLabel = $state('');
  let selectedActivity = $state<Activity>();
  let mapData = $state<ProjectMap>();
  let mapObjectId = $state('');
  let mapPanelTab = $state('body');
  let objectPanelTab = $state('body');
  const active = $derived(tabs.find((tab) => tab.id === activeId));
  let layoutHref = $state(untrack(() => (isProjectLayoutPage(path) ? path : '')));
  const projectView = $derived(!layoutHref);
  const activeUrl = $derived(new URL(layoutHref || active?.href || path, 'http://project.local'));
  const layoutLabels: Record<string, string> = {
    overview: 'Project',
    research: 'Research objects',
    map: 'Map',
    activity: 'Activity',
    settings: 'Project settings',
    'agent-connect': 'Agent connect',
    records: 'Research record',
    references: 'References',
  };
  const section = $derived(activeUrl.pathname.split('/')[3] || 'overview');
  const selectionPanels: Record<
    string,
    { hasSelection: boolean; label: string; guidance: string }
  > = $derived({
    research: { hasSelection: Boolean(selectedResearch), label: 'Object details', guidance: '' },
    map: {
      hasSelection: Boolean(mapObjectId),
      label: 'Object details',
      guidance: 'Select an object on the map to see its details.',
    },
    activity: {
      hasSelection: Boolean(selectedActivity),
      label: 'Activity details',
      guidance: 'Select a change to see its details.',
    },
  });
  const selectionPanel = $derived(selectionPanels[section]);
  const toolsVisible = $derived((projectView || selectionPanel?.hasSelection) && !rightClosed);
  const entity = $derived(activeUrl.pathname.split('/')[4]);
  const showLayoutHeading = $derived(
    !['overview', 'agent-connect', 'settings', 'research', 'map', 'activity'].includes(section),
  );
  const projectLayout = $derived(
    ['overview', 'records', 'references', 'settings', 'agent-connect'].includes(section),
  );
  const railSection = $derived(projectView ? 'sessions' : projectLayout ? 'overview' : section);
  const leftPanelTitle = $derived(projectView ? 'Worktrees' : layoutLabels[railSection]);
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
  function navigateLayout(href: string) {
    agentsClosed = false;
    if (href === `/projects/${projectId}/sessions`) href = active?.href || emptyProjectHref();
    navigate(href);
  }
  function emptyProjectHref() {
    return `/projects/${projectId}/sessions?view=empty&branch=${encodeURIComponent(workingBranch)}${selectedWorktree ? `&worktree=${encodeURIComponent(selectedWorktree.id)}` : ''}`;
  }
  function newChat(worktreeId: string | null = selectedWorktree?.id || null) {
    navigate(
      `/projects/${projectId}/sessions/new?draft=${crypto.randomUUID()}${worktreeId ? `&worktree=${encodeURIComponent(worktreeId)}` : ''}`,
    );
  }
  async function selectWorktree(worktree?: ProjectTask) {
    const version = ++routeVersion;
    contextError = '';
    rightMode = 'explorer';
    try {
      if (!(await switchBranch(worktree?.branch || 'main', version, true))) return false;
      if (worktree) cacheTasks([worktree]);
      navigate(tabs.find((tab) => tab.id === activeId)?.href || emptyProjectHref());
      return true;
    } catch (error) {
      contextError = explain(error);
      return false;
    }
  }
  function newWorktreeChat(worktree?: ProjectTask) {
    newChat(worktree?.id || null);
  }

  function cacheTasks(items: ProjectTask[]) {
    knownTasks = { ...knownTasks, ...Object.fromEntries(items.map((task) => [task.id, task])) };
    for (const task of items) query.setQueryData(['project-task', projectId, task.id], task);
  }
  async function readTask(id: string) {
    if (!taskApi) throw new Error('The conversation’s saved files are unavailable');
    const task = await query.fetchQuery({
      queryKey: ['project-task', projectId, id],
      queryFn: () => taskApi.get(projectId, id),
      staleTime: 5000,
    });
    cacheTasks([task]);
    return task;
  }
  const branchTabs = new SvelteMap<string, { tabs: ProjectTab[]; activeId: string }>();
  let tabsBranch = $state('main');
  const mountedTabs = $derived([
    ...new Map(
      [
        ...[...branchTabs.entries()]
          .filter(([branch]) => branch !== tabsBranch)
          .flatMap(([, saved]) => saved.tabs),
        ...tabs,
      ].map((tab) => [tab.id, tab]),
    ).values(),
  ]);
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
    branchTabs.set(workingBranch, { tabs: [...tabs], activeId });
    contextSwitching = routeDriven;
    pendingBranch = files?.selectProjectBranch(branch) || Promise.resolve(false);
    try {
      const selected = await pendingBranch;
      await tick();
      if (selected) {
        const saved = branchTabs.get(branch);
        tabs = saved?.tabs || [];
        activeId = saved?.activeId || '';
        tabsBranch = branch;
      }
      return selected && version === routeVersion;
    } finally {
      pendingBranch = undefined;
      contextSwitching = false;
    }
  }
  function openSession(id: string) {
    const href = `/projects/${projectId}/sessions/${id}`;
    if (page.url.pathname + page.url.search === href) void applyRoute(href, filesEnabled);
    else navigate(href);
  }
  function addRoute(href: string) {
    const tab = projectRouteTab(projectId, href);
    if (!tab) return;
    if (isProjectLayoutPage(href)) {
      layoutHref = href;
      return;
    }
    layoutHref = '';
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
        tabs = restoreProjectTabs(projectId, JSON.stringify(saved.tabs));
        const activeUrl =
          typeof saved.activeHref === 'string'
            ? new URL(saved.activeHref, 'http://project.local')
            : undefined;
        const activeHref = activeUrl
          ? canonicalUiLocation(activeUrl.pathname, activeUrl.search) + activeUrl.hash
          : '';
        activeId = tabs.find((tab) => tab.href === activeHref)?.id || tabs.at(-1)?.id || '';
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
    if (path === `/projects/${projectId}`) {
      const href = `/projects/${projectId}/${canChat ? 'sessions/new' : 'overview'}`;
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
    const url = new URL(href, 'http://project.local');
    if (!url.pathname.endsWith('/files')) files?.cancelProjectFileLoad();
    contextError = '';
    try {
      if (url.pathname === `/projects/${projectId}`) return;
      const emptyView =
        url.pathname === `/projects/${projectId}/sessions` &&
        url.searchParams.get('view') === 'empty';
      const routeTab = projectRouteTab(projectId, href);
      let targetBranch: string | undefined;
      if (emptyView) {
        const worktreeId = url.searchParams.get('worktree');
        targetBranch = worktreeId
          ? (await readTask(worktreeId)).branch
          : url.searchParams.get('branch') || 'main';
      } else if (routeTab?.kind === 'chat') {
        const sessionId = url.pathname.split('/')[4];
        const taskId =
          sessionId === 'new'
            ? url.searchParams.get('worktree')
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
      if (emptyView) {
        layoutHref = '';
        activeId = '';
        return;
      }
      if (url.pathname.endsWith('/files')) {
        const view = url.searchParams.get('view');
        const id = url.searchParams.get('tab');
        if (view === 'history' || view === 'merge') {
          openFileView(view, false);
          if (view === 'history' && repositoryReady) void files?.loadProjectHistory();
        } else if (id && fileItems.some((item) => item.id === id)) {
          layoutHref = '';
          files?.selectProjectFile(id);
          activeId = `file:${id}`;
        } else if (url.searchParams.get('file') && repositoryReady) {
          const name = url.searchParams.get('file')!;
          const existing = fileItems.find((item) => item.path === name);
          if (existing) {
            layoutHref = '';
            files?.selectProjectFile(existing.id);
            activeId = `file:${existing.id}`;
          } else void files?.openProjectFile(name);
        } else if (currentFileId) {
          layoutHref = '';
          activeId = `file:${currentFileId}`;
        } else addRoute(href);
      } else addRoute(href);
    } catch (error) {
      if (version !== routeVersion) return;
      contextError = explain(error);
      if (active) navigate(active.href, true);
    }
  }
  $effect(() => {
    const saved = {
      activeHref: active?.href,
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
    const staleDiff = (tab: ProjectTab) =>
      tab.kind === 'diff' &&
      new URL(tab.href, 'http://project.local').searchParams.get('branch') !== workingBranch;
    const replaced = tabs.find(
      (tab) =>
        tab.kind === 'file' && tab.preview && !items.some((item) => `file:${item.id}` === tab.id),
    );
    const replacement =
      replaced &&
      items.find((item) => item.preview && !tabs.some((tab) => tab.id === `file:${item.id}`));
    if (replaced && replacement && !contextSwitching) {
      const next = {
        ...replaced,
        id: `file:${replacement.id}`,
        label: replacement.label,
        dirty: replacement.dirty,
        preview: replacement.preview,
        href: fileHref(replacement),
      };
      tabs = tabs.map((tab) => (tab.id === replaced.id ? next : tab));
      if (activeId === replaced.id) activeId = next.id;
    }
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
        return file
          ? {
              ...tab,
              label: file.label,
              dirty: file.dirty,
              preview: file.preview,
              href: fileHref(file),
            }
          : tab;
      });
    const currentTab = tabs.find((tab) => tab.id === activeId);
    if (
      currentTab?.kind === 'file' &&
      previousHref !== currentTab.href &&
      page.url.pathname + page.url.search === previousHref
    )
      navigate(currentTab.href, true);
    if (lostActive && !contextSwitching) {
      const href = `/projects/${projectId}/files?branch=${encodeURIComponent(workingBranch)}`;
      addRoute(href);
      navigate(href);
    }
  }
  function fileHref(file: { id: string; path: string }) {
    return `/projects/${projectId}/files?${file.path ? `file=${encodeURIComponent(file.path)}` : `tab=${encodeURIComponent(file.id)}`}&branch=${encodeURIComponent(workingBranch)}`;
  }
  async function openFile(id?: string) {
    await tick();
    const selected = id || currentFileId;
    const file = fileItems.find((item) => item.id === selected);
    if (!file) {
      navigate(`/projects/${projectId}/files`);
      return;
    }
    const tabId = `file:${selected}`;
    const href = fileHref(file);
    tabs = tabs.filter((tab) => tab.id !== 'files:');
    if (!tabs.some((tab) => tab.id === tabId))
      tabs = [
        ...tabs,
        {
          id: tabId,
          kind: 'file',
          label: file.label,
          dirty: file.dirty,
          preview: file.preview,
          href,
        },
      ];
    layoutHref = '';
    activeId = tabId;
    if (page.url.pathname + page.url.search !== href) navigate(href);
  }
  function openFileView(view: 'history' | 'merge', changeUrl = true) {
    const id = `diff:${view}`;
    const href = `/projects/${projectId}/files?view=${view}&branch=${encodeURIComponent(workingBranch)}`;
    if (!tabs.some((tab) => tab.id === id))
      tabs = [
        ...tabs,
        { id, kind: 'diff', label: view === 'history' ? 'File history' : 'Merge review', href },
      ];
    else tabs = tabs.map((tab) => (tab.id === id ? { ...tab, href } : tab));
    layoutHref = '';
    activeId = id;
    if (changeUrl && page.url.pathname + page.url.search !== href) navigate(href);
  }
  function selectTab(id: string) {
    const tab = tabs.find((item) => item.id === id);
    if (!tab) return;
    files?.cancelProjectFileLoad();
    if (tab.kind === 'file' && !files?.selectProjectFile(id.slice(5))) return;
    if (tab.kind === 'file') activeId = id;
    if (page.url.pathname + page.url.search === tab.href) void applyRoute(tab.href, filesEnabled);
    else navigate(tab.href);
  }
  function updateTab(id: string, state: { label?: string; dirty: boolean }) {
    untrack(() => {
      for (const [branch, saved] of branchTabs) {
        if (branch === tabsBranch) continue;
        const cached = saved.tabs.find((item) => item.id === id);
        if (
          cached &&
          (cached.dirty !== state.dirty || (state.label && cached.label !== state.label))
        )
          branchTabs.set(branch, {
            ...saved,
            tabs: saved.tabs.map((item) =>
              item.id === id
                ? { ...item, label: state.label || item.label, dirty: state.dirty }
                : item,
            ),
          });
      }
      const tab = tabs.find((item) => item.id === id);
      if (tab && (tab.dirty !== state.dirty || (state.label && state.label !== tab.label)))
        tabs = tabs.map((item) =>
          item.id === id ? { ...item, label: state.label || item.label, dirty: state.dirty } : item,
        );
    });
  }
  function created(oldId: string, id: string) {
    if (!tabs.some((tab) => tab.id === oldId)) {
      const replacement = projectRouteTab(projectId, `/projects/${projectId}/sessions/${id}`);
      if (replacement)
        for (const [branch, saved] of branchTabs) {
          if (saved.tabs.some((tab) => tab.id === oldId))
            branchTabs.set(branch, {
              tabs: saved.tabs.map((tab) => (tab.id === oldId ? replacement : tab)),
              activeId: saved.activeId === oldId ? replacement.id : saved.activeId,
            });
        }
      return;
    }
    tabs = tabs.filter((tab) => tab.id !== oldId);
    navigate(`/projects/${projectId}/sessions/${id}`);
  }
  function closeTab(id: string) {
    const tab = tabs.find((item) => item.id === id);
    if (!tab) return;
    if (tab.kind === 'file') {
      if (!files?.closeProjectFile(id.slice(5))) return;
    } else if (tab.dirty && !confirm(`Discard unsaved changes in ${tab.label}?`)) return;
    if (tab.kind === 'object')
      drafts.delete(
        `${projectId}:${new URL(tab.href, 'http://project.local').pathname.split('/')[4]}`,
      );
    const index = tabs.findIndex((item) => item.id === id);
    tabs = tabs.filter((item) => item.id !== id);
    if (activeId === id) {
      activeId = '';
      const next = tabs[Math.min(index, tabs.length - 1)];
      if (next) selectTab(next.id);
      else navigate(emptyProjectHref());
    }
  }

  function reorder(ids: string[]) {
    tabs = ids.flatMap((id) => {
      const tab = tabs.find((item) => item.id === id);
      return tab ? [tab] : [];
    });
  }
  function inspect() {
    if (!projectView && !selectionPanel) {
      agentsClosed = false;
      if (matchMedia('(max-width:760px)').matches) mobilePanel = 'agents';
      return;
    }
    rightMode = 'details';
    rightClosed = false;
    if (matchMedia('(max-width:760px)').matches) mobilePanel = 'tools';
  }
  function hasUnsavedDrafts() {
    return (
      tabs.some((tab) => tab.dirty) ||
      [...branchTabs.entries()].some(
        ([branch, saved]) => branch !== workingBranch && saved.tabs.some((tab) => tab.dirty),
      ) ||
      files?.hasUnsavedProjectFiles()
    );
  }
  beforeNavigate(({ to, cancel }) => {
    if (
      to &&
      [`/projects/${projectId}`, `/projects/${projectId}`].some(
        (root) => to.url.pathname === root || to.url.pathname.startsWith(`${root}/`),
      )
    )
      return;
    if (hasUnsavedDrafts() && !confirm('Leave this project and discard unsaved drafts?')) cancel();
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
    if (hasUnsavedDrafts()) event.preventDefault();
  }}
/>
<ProjectFiles
  {projectId}
  bind:this={files}
  bind:enabled={filesEnabled}
  bind:busy={filesBusy}
  bind:branch={workingBranch}
  {branchLabels}
  active={projectView && active?.kind === 'file'}
  toolsView={rightMode === 'source-control' ? 'source-control' : 'explorer'}
  view={fileView}
  onFileOpen={openFile}
  onTabsChange={syncFiles}
  onOpenView={openFileView}
  onCloseView={(view) => closeTab(`diff:${view}`)}
>
  {#snippet children(editor, navigator)}
    <div class="project-shell">
      <div
        class="project-body"
        class:resizing={Boolean(drag)}
        style={`--agent-width:${!agentsClosed ? agentWidth : 0}px;--agent-handle:${!agentsClosed ? 1 : 0}px;--tools-width:${toolsVisible ? rightWidth : 0}px;--tools-handle:${toolsVisible ? 1 : 0}px;--rail-width:56px`}
      >
        <div class="project-rail">
          <ProjectNavigationRail
            {auth}
            {projectId}
            section={['settings', 'agent-connect'].includes(section) ? section : railSection}
            canManage={project.current_user_role === 'OWNER'}
            showBrand={agentsClosed}
            onNavigate={navigateLayout}
          />
        </div>
        {#if !agentsClosed}<aside class="project-agents" aria-label={`${leftPanelTitle} panel`}>
            <div class="conversation-panel" hidden={!projectView}>
              <ProjectWorktrees
                {projectId}
                activeSessionId={section === 'sessions' ? entity : undefined}
                canReadChats={canWrite}
                {canChat}
                onNewChat={newWorktreeChat}
                activeWorktreeId={selectedWorktree?.id}
                repositoryEnabled={filesEnabled}
                canCreate={canWrite}
                onSelectWorktree={selectWorktree}
                onWorktreesChange={cacheTasks}
                onOpenSession={openSession}
              />
            </div>
            {#if !projectView}<div class="layout-panel">{@render layoutPanel()}</div>{/if}
          </aside>
          <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
          <div
            class="splitter agents-splitter"
            role="separator"
            aria-label="Resize left panel"
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
        <section class="project-center" aria-label="Project workbench">
          <div class="project-tabbar">
            <div class="tabbar-controls" class:desktop-hidden={!agentsClosed}>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Open navigation"
                onclick={() => (mobilePanel = 'navigation')}
                class="mobile-toggle"><Menu size={16} /></Button
              >
              {#if showLayoutHeading}<span class="compact-project-name" title={project.name}
                  >{project.name}</span
                >{/if}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={agentsClosed ? 'Show left panel' : 'Hide left panel'}
                onclick={() => {
                  if (matchMedia('(max-width:760px)').matches) mobilePanel = 'agents';
                  else agentsClosed = false;
                }}><PanelLeftOpen size={16} /></Button
              >
            </div>
            {#if projectView}<ProjectTabStrip
                {tabs}
                {activeId}
                onselect={selectTab}
                onclose={closeTab}
                onreorder={reorder}
                onpin={(id) => {
                  if (id.startsWith('file:')) files?.pinProjectFile(id.slice(5));
                }}
                onnewchat={canChat && !selectedWorktree?.archived_at ? () => newChat() : undefined}
              />{:else if showLayoutHeading}<div class="layout-heading">
                {layoutLabels[section]}
              </div>{/if}
            {#if projectView || selectionPanel?.hasSelection}<div
                class="tabbar-controls tools-toggle"
                class:desktop-hidden={!rightClosed}
              >
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
            {/if}
          </div>
          {#if contextError}<div class="context-error" role="alert">{contextError}</div>{/if}
          <main id="main" class="project-main" tabindex="-1">
            {#if layoutHref}<div class="project-page">
                <ProjectPage
                  {project}
                  href={layoutHref}
                  active={true}
                  onState={() => {}}
                  onCreated={() => {}}
                  onInspect={inspect}
                  bind:selectedResearch
                  bind:researchCreationOpen
                  bind:researchCountLabel
                  bind:selectedActivity
                  bind:mapData
                  bind:mapObjectId
                  bind:mapPanelTab
                />
              </div>{/if}
            {#if projectView && !active}<div class="workbench-empty">
                Open a conversation or file to get started.
              </div>{/if}
            {#each mountedTabs.filter((tab) => tab.kind !== 'file' && tab.kind !== 'diff' && tab.id !== 'files:') as tab (tab.id)}
              <div class="project-page" hidden={!projectView || tab.id !== activeId}>
                <ProjectPage
                  {project}
                  href={tab.href}
                  active={projectView && tab.id === activeId}
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
              class="project-file-page"
              hidden={!projectView ||
                (active?.kind !== 'file' && active?.kind !== 'diff' && active?.id !== 'files:')}
            >
              {@render editor()}
            </div>
          </main>
        </section>
        {#if toolsVisible}
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
          <aside class="project-tools" aria-label={selectionPanel?.label ?? 'Project tools'}>
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
            ? (selectionPanel?.label ?? 'Project tools')
            : mobilePanel === 'agents'
              ? leftPanelTitle
              : 'Navigation'}</Sheet.Title
        >
        <div class="mobile-panel">
          {#if mobilePanel !== 'tools'}
            <header class="panel-heading" class:left-panel-controls={mobilePanel === 'agents'}>
              {#if mobilePanel === 'navigation'}<span>Navigation</span>{/if}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Close drawer"
                onclick={() => (mobilePanel = undefined)}><X size={14} /></Button
              >
            </header>
          {/if}
          {#if mobilePanel === 'navigation'}<ProjectNavigationRail
              {auth}
              {projectId}
              section={['settings', 'agent-connect'].includes(section) ? section : railSection}
              canManage={project.current_user_role === 'OWNER'}
              expanded
              showBrand={false}
              onNavigate={navigateLayout}
            />
          {:else if mobilePanel === 'agents' && !projectView}<div class="layout-panel">
              {@render layoutPanel()}
            </div>
          {:else if mobilePanel === 'agents'}<ProjectWorktrees
              {projectId}
              activeSessionId={section === 'sessions' ? entity : undefined}
              canReadChats={canWrite}
              {canChat}
              onNewChat={newWorktreeChat}
              activeWorktreeId={selectedWorktree?.id}
              repositoryEnabled={filesEnabled}
              canCreate={canWrite}
              onSelectWorktree={selectWorktree}
              onWorktreesChange={cacheTasks}
              onOpenSession={openSession}
            />
          {:else if mobilePanel === 'tools'}{@render tools('mobile', navigator)}{/if}
        </div>
      </Sheet.Content></Sheet.Root
    >
  {/snippet}
</ProjectFiles>
{#snippet layoutPanel()}
  <ProjectPanelHeader title={leftPanelTitle} />
  <div class="layout-panel-content">
    {#if projectLayout}
      <nav class="project-links" aria-label="Project pages">
        {#each [['overview', 'Overview'], ['agent-connect', 'Agent connect'], ...(project.current_user_role === 'OWNER' ? [['settings', 'Settings']] : [])] as [id, label] (id)}
          <a
            href={`/projects/${projectId}/${id}`}
            aria-current={section === id ? 'page' : undefined}
            onclick={(event) => {
              if (
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
              )
                return;
              event.preventDefault();
              navigate(`/projects/${projectId}/${id}`);
            }}>{label}</a
          >
        {/each}
      </nav>
    {/if}
    {#if section === 'research'}
      <div class="research-controls">
        {#if researchCountLabel}<p>{researchCountLabel}</p>{/if}
        {#if canWrite}<Button
            variant="outline"
            aria-haspopup="dialog"
            onclick={async () => {
              mobilePanel = undefined;
              await tick();
              researchCreationOpen = true;
            }}>Create object</Button
          >{/if}
      </div>
    {:else if selectionPanel}
      <p class="selection-guidance">{selectionPanel.guidance}</p>
    {:else if section !== 'overview'}
      <ProjectSectionPanel
        {project}
        {section}
        bind:selected={selectedActivity}
        bind:selectedResearch
      />
    {/if}
  </div>
{/snippet}
{#snippet tools(placement: 'desktop' | 'mobile', navigator?: Snippet)}
  {@const closeLabel =
    placement === 'mobile' ? 'Close drawer' : selectionPanel ? 'Close details' : 'Collapse tools'}
  <Tooltip.Provider delayDuration={250}>
    <header class="tools-header">
      {#if selectionPanel}<span class="details-heading">Details</span>{:else}<div
          class="tool-switcher"
          role="tablist"
          aria-label="Project tools"
        >
          {#each [['explorer', 'Explorer', FolderOpen], ['source-control', 'Source control', GitBranch], ['details', section === 'objects' ? 'Details' : 'Agent history', section === 'objects' ? Info : History]] as const as [id, label, Icon] (id)}
            <Tooltip.Root>
              <Tooltip.Trigger>
                {#snippet child({ props })}
                  <button
                    {...props}
                    role="tab"
                    aria-label={label}
                    aria-selected={rightMode === id}
                    disabled={filesBusy}
                    onclick={() => (rightMode = id)}><Icon size={14} aria-hidden="true" /></button
                  >
                {/snippet}
              </Tooltip.Trigger>
              <Tooltip.Content class="text-[11px] px-2 py-1">{label}</Tooltip.Content>
            </Tooltip.Root>
          {/each}
        </div>{/if}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <Button
              {...props}
              variant="ghost"
              size="icon-sm"
              aria-label={closeLabel}
              onclick={() => {
                if (placement === 'desktop') rightClosed = true;
                else mobilePanel = undefined;
              }}
              >{#if placement === 'desktop'}<PanelRightClose size={14} />{:else}<X
                  size={14}
                />{/if}</Button
            >
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content class="text-[11px] px-2 py-1">
          {closeLabel}
        </Tooltip.Content>
      </Tooltip.Root>
    </header>
  </Tooltip.Provider>
  <div class="tool-content">
    {#if selectionPanel}<div class="selection-details">
        <ProjectSectionPanel
          {project}
          {section}
          bind:selected={selectedActivity}
          bind:selectedResearch
          {mapData}
          bind:mapObjectId
          bind:mapPanelTab
        />
      </div>
    {:else if rightMode !== 'details'}{#if navigator}{@render navigator()}{:else}<p
          class="tool-empty"
        >
          {filesEnabled ? 'Loading files…' : 'File storage is unavailable for this project.'}
        </p>{/if}
    {:else if section === 'sessions'}<div data-chat-panel-host={placement}></div>
      {#if entity === 'new' || !entity}<p class="tool-empty">
          Start a conversation to see its agent run history.
        </p>{/if}
    {:else if section === 'objects' && entity}{#key entity}<ProjectObjectPanel
          {projectId}
          objectId={entity}
          publicRead={false}
          bind:activeTab={objectPanelTab}
        />{/key}
    {:else}<p class="tool-empty">Open a conversation to see its agent run history.</p>{/if}
  </div>
{/snippet}

<style>
  .research-controls {
    display: grid;
    gap: 12px;
  }
  .research-controls p {
    margin: 0;
    color: var(--muted-foreground);
    font-size: 12px;
  }
  .selection-guidance {
    margin: 0;
    color: var(--muted-foreground);
    font-size: 12px;
    line-height: 1.5;
  }
  .selection-details {
    padding: 12px;
  }
  .details-heading {
    font-size: 12px;
    font-weight: 600;
  }
  .workbench-empty {
    display: grid;
    place-items: center;
    height: 100%;
    padding: 24px;
    color: var(--muted-foreground);
    font-size: 13px;
    text-align: center;
  }
  .conversation-panel {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }
  .conversation-panel[hidden] {
    display: none;
  }
  .layout-panel {
    display: flex;
    flex-direction: column;
    gap: 12px;
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 0 12px 12px;
  }
  .layout-panel-content {
    min-width: 0;
  }
  .layout-heading {
    display: flex;
    align-items: center;
    flex: 1;
    height: var(--project-nav-height);
    box-sizing: border-box;
    padding: 0 12px;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
    font-weight: 600;
    line-height: 16px;
  }
  .project-links {
    display: grid;
    gap: 4px;
    margin-bottom: 24px;
  }
  .project-links a {
    padding: 8px;
    border-radius: 6px;
    font-size: 13px;
    color: var(--muted-foreground);
    text-decoration: none;
  }
  .project-links a:hover,
  .project-links a[aria-current='page'] {
    color: var(--brand-strong);
    background: var(--brand-soft);
  }

  .context-error {
    padding: 10px 16px;
    color: var(--destructive);
    background: var(--accent-soft);
    font-size: 12px;
  }
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
      var(--rail-width) var(--agent-width) var(--agent-handle) minmax(0, 1fr)
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
  .project-center {
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
  .project-page {
    height: 100%;
    overflow: auto;
    padding: 24px;
  }
  .project-file-page {
    height: 100%;
    min-height: 0;
  }
  .project-main [hidden] {
    display: none !important;
  }
  .project-tools {
    grid-column: 6;
    grid-row: 1;
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    background: var(--sidebar);
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
  .tools-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: var(--project-nav-height);
    box-sizing: border-box;
    padding: 0 12px;
    border-bottom: 1px solid var(--border);
    background: var(--sidebar);
    flex-shrink: 0;
  }
  .tool-switcher {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .tool-switcher button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    border-radius: 4px;
    color: var(--muted-foreground);
  }
  .tool-switcher button[aria-selected='true'] {
    color: var(--sidebar-accent-foreground);
    background: var(--sidebar-accent);
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
  .tabbar-controls :global(button),
  .tools-header > :global(button),
  .panel-heading :global(button) {
    width: 20px;
    height: 20px;
    min-height: 0;
    padding: 0;
  }
  .tabbar-controls :global(button svg),
  .tools-header > :global(button svg),
  .panel-heading :global(button svg) {
    width: 14px;
    height: 14px;
  }
  @media (max-width: 1050px) and (min-width: 761px) {
    .project-body {
      grid-template-columns:
        var(--rail-width) min(var(--agent-width), 220px) var(--agent-handle)
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
    .project-page {
      padding: 16px;
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
</style>
